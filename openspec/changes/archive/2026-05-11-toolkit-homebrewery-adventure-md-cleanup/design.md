## Context

The parent change `toolkit-homebrewery-module-adventure-md` built the adventure writer with a BU-file-first loading strategy and default V3 templates from `toolkit-homebrewery-style-definitions`. Live Homebrewery editor review of the generated `The_Ancients_Lab/MODULE_SUMMARY.md` revealed 8 issues that this cleanup change addresses. The fixes are narrow — no architectural restructuring of the writer pipeline.

## Goals / Non-Goals

**Goals:**
- Fix all 8 issues identified in live review.
- Merge narrative-enriched live file data into BU-loaded structures.
- Correct heading levels, metadata format, and stat block template.
- Add plot abstract via LLM summarization with deterministic fallback.
- Regenerate The Ancients Lab MODULE_SUMMARY.md with all fixes applied.

**Non-Goals:**
- No image insertion (deferred).
- No schema changes.
- No runtime game engine modifications.

## Decisions

### Decision 1: BU-first with live merge, not live-first

**Rationale:** `_BU` files represent the canonical shipped module structure. The live files contain narrative enrichment (Lovecraftian NPC descriptions, plot point details) added by enrichment passes. Merging live data into BU preserves structural authority while surfacing enrichment.

**Merge rules:**
1. NPCs: If BU NPC description is empty or <50 chars, overlay from live.
2. Plot points: If BU description is shorter than live, overlay from live.
3. Areas: BU provides canonical topology; live may have richer area descriptions.
4. Author/license: BU fields are empty; always overlay from live if available.
5. Field-specific: `description` overlays only when BU empty; `role`/`faction` always overlay from live when present.

### Decision 2: HTML comment metadata

**Rationale:** The Homebrewery editor detects `<!-- metadata\ntitle: ...\n...\n-->` as metadata. Triple-backtick code fences render as visible text blocks in the editor preview. The HTML comment approach is the standard documented format.

**Template change:**
```python
# Before
METADATA_TEMPLATE = """```metadata\ntitle: '{title}'\n...\n```\n"""
# After
METADATA_TEMPLATE = """<!--\nmetadata\ntitle: '{title}'\n...\n-->\n"""
```

### Decision 3: H1 for main sections

**Rationale:** Homebrewery renders `# Title` as a wide-block header spanning the full page width. `## Title` is a normal inline heading. The main document sections (Plot Overview, NPC Gallery, Locations, Appendices) benefit from the wide-block visual separation.

**Affected headings:**
- `## Plot Overview` → `# Plot Overview`
- `## NPC Gallery` → `# NPC Gallery`
- `## Locations` → `# Locations`
- `## Credits` → `# Credits` (inside `{{credits}}` block, kept as-is per Homebrewery convention)

### Decision 4: H3 stat block names with attack formatting

**Rationale:** In Homebrewery, `> ### Name` renders as an underlined H3 within the stat block blockquote, visually distinct from the surrounding serif text. Actions need full 5e attack syntax for DM reference.

**Stat block template revision:**

```markdown
___
___
> ### {name}
> *{size} {creature_type}, {alignment}*
> ___
> - **Armor Class** {armor_class}
> - **Hit Points** {hit_points}
> - **Speed** {speed}
>___
>|STR|DEX|CON|INT|WIS|CHA|
>|:---:|:---:|:---:|:---:|:---:|:---:|
>|{str_score} ({str_mod})|...|
>___
{abilities_section}
{actions_section}
```

**Action formatting:**
```
> ***Bite.*** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 6 (2d4 + 2) piercing damage.
```

Derived from structured monster data: `attackBonus`, `damageDice`, `damageBonus`, `damageType`.

**Special ability formatting** (separate from actions):
```
> ***Keen Hearing and Smell.*** The wolf has advantage on Wisdom (Perception) checks that rely on hearing or smell.
```

### Decision 5: LLM plot abstract with fail-open

**Rationale:** A raw dump of 13 plot points is not useful as an introduction. An LLM-summarized 2-3 paragraph abstract provides narrative context. The DM summarization model (`DM_SUMMARIZATION_MODEL`) is already configured and has low latency/low cost.

**Fail-open behavior:** If the LLM call fails (timeout, provider error, imports unavailable), fall back to deterministic concatenation: first two sentences of PP001 + "The adventure culminates in..." + last two sentences of final plot point.

**Token budget:** Plot text is ~8KB for 13 well-described points. Summary prompt adds ~200 tokens. LLM response capped at 400 tokens. Total cost: ~$0.001 per generation.

### Decision 6: Area deduplication by areaId

**Rationale:** `load_module_data()` iterates `sorted(areas_dir.glob("*.json"))` which matches both `BA001.json` and `BA001_BU.json`. `_prefer_bu()` redirects both to `BA001_BU.json`, producing two identical entries. Fix: maintain a set of seen area IDs and skip duplicates on insertion.

## Architecture

No structural changes to the writer pipeline. The fixes are localized:

```
load_module_data()
  ├── [NEW] _merge_live_narrative(ctx_bu, ctx_live)  -- merge NPC/plot/area data
  ├── [NEW] dedup by areaId after loading
  ├── [FIX] read areaName instead of locationName
  └── [FIX] author/license fallback to live (already done)

generate_homebrewery_adventure()
  ├── [FIX] _build_cover_page()  -- metadata format
  ├── [FIX] _build_intro_section()  -- H1 heading
  ├── [NEW] _build_plot_abstract()  -- LLM summary
  ├── [FIX] _build_plot_overview()  -- H1 heading
  ├── [FIX] _build_npc_gallery()  -- H1 heading
  ├── [FIX] _build_locations_section()  -- H1 heading, areaName
  ├── [FIX] _build_monster_appendix()  -- H3 names, attack formatting
  ├── [FIX] _build_items_appendix()  -- H1 heading
  └── [_]   _build_credits()  -- no changes (already correct)

utils/homebrewery_style.py
  ├── [FIX] METADATA_TEMPLATE  -- HTML comment format
  └── [FIX] MONSTER_STATBLOCK_TEMPLATE  -- H3 names, separate abilities/actions
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| LLM plot abstract costs money | Fail-open fallback is free. LLM call only invoked during explicit adventure generation, not during normal gameplay. |
| Live file may have been mutated by gameplay | Only narrative text fields are merged (descriptions, roles, factions). Mechanical state (HP, status) is never read from live files. |
| HTML comment metadata breaks older Homebrewery clones | The HTML comment format is the documented standard for current Homebrewery. Older clones are not a target. |
| Attack formatting diverges from 5e conventions | Format matches SRD stat block style exactly: `*Hit:* X (YdZ + B) damage type.` |

## Migration Plan

- The style module template changes are additive (old templates remain available via `MONSTER_STATBLOCK_TEMPLATE` constant, which is overwritten with the new format).
- Existing callers of `format_monster_statblock()` continue to work — the function signature is unchanged.
- MODULE_SUMMARY.md is regenerated in place.
