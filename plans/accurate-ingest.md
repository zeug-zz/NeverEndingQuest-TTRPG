# Accurate Homebrew Ingest: Structured Pre-Extraction Layer

**Status:** DRAFT
**Date:** 2026-05-04
**Target:** Fix the 95% fidelity loss between original adventure markdown and ingested NEQ module, as observed with The Hidden City of Numillian.

---

## Problem

### The Numillian Case Study

Original MD (`Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`, 250 lines):
- 20 named NPCs with distinct personalities (Wayne the crooked-toothed innkeeper, Belrik Dumma-dhur the duergar assassin, Irene Laughing-Eyes the cat wizard, Dog-Growl/Book-shut/Deflation the kenku composers, etc.)
- 13 specific locations with map-key entries (Charion Tamer, Shuluth's Tomb, The Rookery, Grove, Brooksteps Inn, Wizard's Tower, Art Gallery, Temple of Broance, etc.)
- A tight, character-driven plot: Gatepact lore -> Trial at the Door (skull riddle, flooding room puzzle, kill-the-dog mindscape test) -> City of the Mind -> protect Kobe

Ingested module (`modules/The_Hidden_City_of_Numillian/`):
- 2 of 20 NPCs survive (Kobe and Shuluth — both heavily re-characterized)
- 0 of 13 locations survive (replaced by 5 generic area IDs)
- Plot completely replaced by an 18-beat ward-network conspiracy thriller
- Module tone: "lush quirky character-driven" -> "generic conspiracy thriller"

**Shared DNA: ~3%** (the words "Numillian", "Shuluth", "Kobe", and the concept of "hidden city" + "trials").

### Root Cause

The Toolkit Homebrew Upload pipeline (Path C) has a single-point compression bottleneck:

```
Markdown (250 lines, 20 NPCs, 13 locations, specific puzzles)
    |
    v   ONE LLM call: "extract everything into this JSON schema"
    |
Normalized packet (10 npc_seeds, 5 locations, generic summary)
    |
    v   builder_narrative: 3-7 line prose summary
    |
ModuleBuilder.build_module(narrative)
    |
    v   MANY LLM calls: expand from the compressed summary
    |
Output module (2 NPCs survive, 0 locations, new plot)
```

Each step loses fidelity:
1. **Normalizer compression** — The LLM reads 250 lines and must produce a flat JSON with `npc_seeds`, `locations`, `plot_progression`, `builder_narrative`, etc. The attention mechanism favors the "gist" over exhaustive extraction. NPCs buried in tables or spread across map-key subsections are invisible.
2. **Builder re-expansion** — The ModuleBuilder receives a 3-7 line summary and hallucinates 90% of the content from its own defaults. It has no source of truth for entity names.
3. **No fidelity check** — Nothing compares the normalized output against the original to flag dropped entities.

### Why Path A (Deterministic) Doesn't Help

The `homebrewery_importer.py` deterministic path expects `## Room N:` format. Numillian uses `### N. LocationName` subsections under a `## Map Key` parent. The importer's `_parse_room_blocks` regex only matches `^##\s+Room\s+\d+:` and silently skips everything else. Even if we generalized the room pattern, the non-room content (Gatepact lore, Trial procedures, NPC tables) wouldn't map.

---

## Solution: Structured Pre-Extraction Layer

Add a Python-side pre-processing step that mechanically extracts structured data from the markdown *before* the LLM sees it. Feed the extraction as a "manifest" alongside the raw text so the LLM has a cheat sheet. Then verify fidelity before the builder runs.

### Architecture

```
Markdown
    |
    v   Step 1: Python mechanical extraction
    |
Source Manifest {
    typed_sections:    [heading, content, type]
    extracted_tables:  [context, headers, rows]
    named_entities:    [name, context, entity_type]
    numeric_locations: [number, name, description]
    bold_spans:        [text, section_context]
}
    |
    v   Step 2: LLM normalization (now manifest-aware)
    |
    Raw markdown + Source Manifest + Fidelity instructions
    |
    v
Normalized packet (all entities preserved)
    |
    v   Step 3: Fidelity diff (mechanical, no LLM)
    |
Compare: manifest.named_entities vs packet.npc_seeds
         manifest.numeric_locations vs packet.locations
    |
    v   Step 4: Entity-rich builder narrative
    |
Builder narrative includes full entity catalog inline
    |
    v   Step 5: ModuleBuilder.build_module(narrative)
    |
Output: faithful module
```

### Key Principle

> **Python mechanically extracts what it can. LLM enriches but does not drop or rename.**

The manifest becomes the ground truth. The LLM's job shifts from "discover entities from scratch" to "preserve and enrich pre-extracted entities."

---

## Implementation Details

### Step 1: Source Manifest Extraction

New file: `utils/toolkit_source_manifest.py` (or added to `core/importers/homebrewery_importer.py` as shared utilities).

#### 1a. Heading Hierarchy Extraction

```python
def _extract_heading_hierarchy(md_text: str) -> List[Dict]:
    """
    Extract all headings with their level, text, and content range.
    Returns tree-structure with parent-child relationships.
    
    Example output:
    [
      {"level": 1, "text": "The Hidden City of Numillian", "start": 0},
      {"level": 2, "text": "The Gatepact", "start": 450, "parent": "The Hidden City..."},
      {"level": 2, "text": "Trial at the Door", "start": 1200, "parent": "The Hidden City..."},
      {"level": 3, "text": "Worthy of Knowledge", "start": 1400, "parent": "Trial at the Door"},
      ...
    ]
    """
```

Pattern: `^(#{1,6})\s+(.+)$` with position tracking.

#### 1b. Markdown Table Extraction

Already exists: `homebrewery_importer._extract_markdown_tables()`. Move to shared utility.

For Numillian, this captures:
- The "Numillian NPCs" table (9 NPCs with roles)
- The "There is no Spoon" mistakes table

#### 1c. Map-Key Location Parser

```python
def _parse_map_key_locations(md_text: str) -> List[Dict]:
    """
    Detect map-key sections and extract numbered locations.
    
    Covers patterns:
      ### 1. Location Name    (Numillian style)
      ### 1 Location Name     (alternative)
      ### 1 - Location Name   (with dash)
      #### 1. Sub-location     (deeper nesting)
    
    Returns:
    [
      {"number": 1, "name": "Charion Tamer", "description": "This small cottage...", 
       "npc_mentions": ["Bramak Pakel"], "raw_content": "..."},
      ...
    ]
    """
```

Detection: find a parent heading (like `## Map Key` or `## Locations`) followed by numbered subsections. Match with `^#{3,4}\s+(\d+)[\.\)\-\s]+(.+)$`.

For each location entry:
- Extract the name
- Collect all bold names within the description as NPC mentions
- Capture the full description text
- Note any sub-sections (like #### DM Notes)

#### 1d. Named Entity Extraction

```python
def _extract_named_entities_from_text(text: str, section_context: str) -> List[Dict]:
    """
    Extract named entities using multiple signals:
    1. Bold spans: **Name** or **Name the Title**
    2. Table cells with title-cased multi-word names
    3. Quoted names: "Name"
    4. Proper noun patterns: [A-Z][a-z]+ [A-Z][a-z]+ (with section-awareness)
    
    Each entity tagged with:
    - name: canonical name as it appears
    - source: "bold_span" | "table_cell" | "quoted" | "proper_noun"
    - context: which section/table it came from
    - entity_type: "npc" | "location" | "item" | "faction" | "unknown"
    """
```

Conservative approach: prefer explicit signals (bold, tables) over pattern-matching. Flag uncertain extractions.

#### 1e. Assemble the Manifest

```python
def build_source_manifest(md_text: str) -> Dict[str, Any]:
    """
    Produce the complete source manifest.
    """
    headings = _extract_heading_hierarchy(md_text)
    tables = _extract_markdown_tables(md_text)
    locations = _parse_map_key_locations(md_text)
    
    # Extract entities from each section
    all_entities = []
    for heading in headings:
        section_text = md_text[heading["start"]:heading.get("end", len(md_text))]
        entities = _extract_named_entities_from_text(section_text, heading["text"])
        all_entities.extend(entities)
    
    # Also extract from tables
    table_entities = _extract_entities_from_tables(tables)
    all_entities.extend(table_entities)
    
    # Deduplicate by normalized name
    unique_entities = _dedupe_entities(all_entities)
    
    return {
        "headings": headings,
        "tables": tables,
        "location_catalog": locations,
        "named_entities": unique_entities,
        "entity_count": len(unique_entities),
    }
```

### Step 2: LLM Normalization with Manifest

Modify `utils/toolkit_homebrew_normalizer.py:_normalize_homebrew_upload()`:

```python
def normalize_homebrew_upload(source_path, workspace, preflight, source_rights_class):
    source_text = source_path.read_text(...)
    
    # NEW: Build source manifest
    source_manifest = build_source_manifest(source_text)
    
    # Include manifest in the LLM request
    request_payload = {
        "source_filename": source_path.name,
        "preflight": preflight,
        "source_text": normalized_source_text,
        "source_manifest": source_manifest,           # <-- NEW
    }
```

The LLM receives the manifest right next to the raw text. It can cross-reference.

### Step 3: Prompt Upgrade

Update `prompts/toolkit/homebrew_upload_normalization_prompt.txt`:

Add these rules:

```
8. The source_manifest contains pre-extracted entities. You MUST include every entity
   from source_manifest.named_entities in your output. Do not drop, rename, or merge
   entities. If the manifest says "Wayne (gnome innkeeper)", your npc_seeds must
   include Wayne with that role.

9. The source_manifest.location_catalog contains pre-parsed locations. You MUST
   include every location in your locations array. Preserve the original names.
   Do not invent new location names when the manifest provides them.

10. For each entity in the manifest, enrich with additional source details (personality,
    faction, relationships) but NEVER change the canonical name.

11. grounded_facts must reference the manifest: "Extracted N entities from source
    manifest (N locations, M NPCs)."

12. If the manifest contains entities you cannot fit into the output schema (e.g., 
    the schema limits array sizes), note this in warnings with explicit entity names.

13. builder_narrative MUST include the full entity catalog inline, not a summary.
    Format: "Module: TITLE. NPCs (N): Name1 (role1), Name2 (role2), ... 
    Locations (M): Loc1, Loc2, ... Plot: ..."
```

### Step 4: Fidelity Verification

After normalization, before builder invocation:

```python
def verify_normalization_fidelity(source_manifest: Dict, normalized_packet: Dict) -> Dict:
    """
    Compare manifest entities against normalized output.
    Returns diff with missing, renamed, and added entities.
    """
    manifest_npcs = {e["name"].lower() for e in source_manifest["named_entities"] 
                     if e["entity_type"] == "npc"}
    packet_npcs = {s["name"].lower() for s in normalized_packet.get("npc_seeds", [])}
    
    manifest_locations = {l["name"].lower() for l in source_manifest.get("location_catalog", [])}
    packet_locations = {l.get("name", "").lower() for l in normalized_packet.get("locations", [])}
    
    return {
        "npc_fidelity": {
            "manifest_count": len(manifest_npcs),
            "packet_count": len(packet_npcs),
            "missing": sorted(manifest_npcs - packet_npcs),
            "added": sorted(packet_npcs - manifest_npcs),
            "preserved": sorted(manifest_npcs & packet_npcs),
        },
        "location_fidelity": {
            "manifest_count": len(manifest_locations),
            "packet_count": len(packet_locations),
            "missing": sorted(manifest_locations - packet_locations),
            "added": sorted(packet_locations - manifest_locations),
            "preserved": sorted(manifest_locations & packet_locations),
        },
        "overall": "pass" if len(manifest_npcs - packet_npcs) == 0 else "degraded",
    }
```

Display in the toolkit review UI:
- Green check: "All N NPCs and M locations preserved"
- Yellow warning: "K entities from source not found in normalization. Builder may lose fidelity."
- Red: "Normalization failed fidelity check (more than 50% entities missing)"

### Step 5: Entity-Rich Builder Narrative

Modify `_build_builder_narrative()` to include the full entity catalog:

```python
def _build_builder_narrative(packet, model_payload):
    # ... existing logic ...
    
    # NEW: Include full entity catalog
    npc_seeds = _as_list(packet.get("npc_seeds"))
    locations = _as_list(packet.get("locations"))
    
    if npc_seeds:
        npc_lines = ["NPCs ({})".format(len(npc_seeds))]
        for n in npc_seeds:
            name = _as_string(n.get("name")) if isinstance(n, dict) else _as_string(n)
            role = _as_string(n.get("role")) if isinstance(n, dict) else ""
            npc_lines.append(f"  - {name}: {role}" if role else f"  - {name}")
        parts.append("\n".join(npc_lines))
    
    if locations:
        loc_names = []
        for l in locations:
            name = _as_string(l.get("name")) if isinstance(l, dict) else _as_string(l)
            if name:
                loc_names.append(name)
        if loc_names:
            parts.append(f"Locations ({len(loc_names)}): {', '.join(loc_names)}")
    
    # ...
```

This gives the ModuleBuilder LLM actual entity names to use in area generation, NPC placement, and plot construction. Instead of "generate a quirky innkeeper", it gets "create content for Wayne, a charming crooked-toothed gnome innkeeper at the Brooksteps Inn."

### Step 6: Generalized Room Parser (for Deterministic Path)

Extend `homebrewery_importer._parse_room_blocks()` to handle non-room formats:

```python
def _parse_content_blocks(semantic_text: str) -> List[Dict]:
    """
    Generalized content block parser that handles multiple heading patterns:
    - ## Room N: Title (existing room-based format)
    - ### N. LocationName (map-key format)
    - ### N - LocationName (dash-separated)
    - #### Sub-location within a parent
    
    Falls back to LLM extraction when no deterministic pattern matches.
    """
    # Try room format first
    rooms = _parse_room_blocks(semantic_text)
    if rooms:
        return rooms
    
    # Try map-key format
    locations = _parse_map_key_locations(semantic_text)
    if locations:
        # Convert location format to room-compatible format
        return [_location_to_room_dict(loc) for loc in locations]
    
    # No deterministic pattern — return empty, let LLM handle it
    return []
```

This ensures that future modules with the same structure as Numillian can use the deterministic path (Path A) directly, bypassing LLM normalization entirely.

---

## Files to Create

| File | Purpose |
|------|---------|
| `utils/toolkit_source_manifest.py` | Shared manifest extraction: headings, tables, locations, entities |

## Files to Modify

| File | Change | Lines |
|------|--------|-------|
| `core/importers/homebrewery_importer.py` | Add `_parse_map_key_locations()`, `_parse_content_blocks()` fallback, expose `_extract_markdown_tables()` | ~80 |
| `utils/toolkit_homebrew_normalizer.py` | Accept and pass `source_manifest` to LLM; updated `_build_builder_narrative` with entity catalog | ~50 |
| `prompts/toolkit/homebrew_upload_normalization_prompt.txt` | Add 6 manifest-fidelity rules (rules 8-13) | ~20 |
| `web/extensions/toolkit_homebrew_packet_builder.py` | Wire manifest extraction before normalization; add fidelity diff display | ~30 |
| `web/routes/toolkit_homebrew_routes.py` | Pass fidelity diff to review UI | ~10 |
| `web/templates/module_toolkit.html` | Show fidelity diff in review panel | ~30 |

## Tests

| Test | What it verifies |
|------|-----------------|
| `test_source_manifest_headings.py` | Heading hierarchy extraction for mixed-level MD |
| `test_source_manifest_tables.py` | Table extraction from various MD table formats |
| `test_source_manifest_locations.py` | Map-key location parser (Numillian format, dash format, plain numbered) |
| `test_source_manifest_entities.py` | Bold-span, table-cell, and proper noun entity extraction |
| `test_source_manifest_integration.py` | End-to-end manifest build for Numillian MD — verifies 20 NPCs + 13 locations |
| `test_normalization_fidelity_check.py` | Fidelity diff: all-preserved, partial-drop, complete-miss scenarios |
| `test_builder_narrative_catalog.py` | Entity catalog inclusion in builder narrative |
| `test_content_blocks_fallback.py` | `_parse_content_blocks()` handles room format, map-key format, and unknown |

## Acceptance Criteria

Run Numillian through the new pipeline:

1. **Source manifest captures**: 18+ NPCs, 13 locations, the Gatepact lore section, the trial mechanics section
2. **Normalized packet preserves**: all manifest NPCs with their original roles, all manifest locations with their original names
3. **Fidelity diff shows**: 0 missing NPCs, 0 missing locations
4. **Builder narrative includes**: full entity catalog (not just a summary)
5. **Output module has**: recognizable versions of Wayne, Treever, Belrik, Bramak, Irene, etc. in their correct locations
6. **Plot structure reflects**: the trial-at-the-door shape (not a generic ward-network conspiracy)
7. **Tone matches**: quirky character-driven feel preserved

## Rollout Strategy

1. **Phase 1: Manifest extraction only** — Add `toolkit_source_manifest.py`, verify Numillian manifest captures everything. No builder changes.
2. **Phase 2: Normalizer prompt + fidelity diff** — Update prompt, add fidelity check to review UI. Pipeline still optional (behind flag or review panel).
3. **Phase 3: Builder narrative enrichment** — Entity-rich narratives flow to ModuleBuilder. The big fidelity win.
4. **Phase 4: Deterministic path expansion** — `_parse_content_blocks()` handles map-key format directly. Some modules can skip LLM normalization entirely.

## Risks

- **Token budget**: Passing the manifest to the normalizer LLM adds overhead. The manifest is structured JSON (compact) and should be under 2K tokens for a 250-line MD. Acceptable.
- **False positive extraction**: Mechanical bold/table extraction may capture non-entity names. Mitigation: entity-type classification + human review before builder runs.
- **Schema limits**: The normalized packet schema restricts array sizes. May need to raise limits for modules with many NPCs/locations. Mitigation: warn in fidelity diff, let user decide.
- **Backward compatibility**: Existing normalized packets lack manifests. Mitigation: manifest is optional — if absent, normalizer falls back to current behavior.
