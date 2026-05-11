## Context

The Homebrewery adventure writer sits at the intersection of three existing systems:

1. **NEQ Module Data:** JSON files in `modules/<slug>/` (module_context.json, module_plot_BU.json, areas/*_BU.json, monsters/*.json, map_*.json)
2. **Homebrewery Style Templates:** `utils/homebrewery_style.py` (from the `toolkit-homebrewery-style-definitions` change)
3. **Toolkit Module Builder GUI:** `web/templates/module_toolkit.html` + `web/web_interface.py` endpoints

This change reads from (1), formats using (2), and exposes through (3).

## Goals / Non-Goals

**Goals:**
- Produce a complete, valid Homebrewery V3 markdown document from NEQ module JSON.
- Handle sparse data (empty fields, missing sections) gracefully with placeholder notes.
- Pilot on The Ancients Lab to verify real-world module data works.
- Add GUI button for one-click download.

**Non-Goals:**
- No PDF generation (separate follow-up change).
- No custom CSS or advanced Homebrewery theming beyond V3 defaults.
- No LLM involvement - deterministic generation only.
- No merging with original community adventure files.

## Decisions

### Decision 1: Single module output file, not per-section files

**Rationale:** Homebrewery expects a single markdown document with `\page` breaks. Splitting into multiple files would require user assembly. A single file can be pasted directly into the Homebrewery editor or downloaded as one `.md` file.

### Decision 2: Deterministic generation, no LLM

**Rationale:** The module data is already authored and enriched. Regenerating prose through an LLM would be slow, expensive, and non-deterministic. The writer assembles existing text into Homebrewery format - it does not create new prose.

**Exception:** If a section has no data at all (e.g., empty area descriptions), the writer inserts a deterministic placeholder note like `*No authored room descriptions are available for this area.*` rather than attempting LLM generation.

### Decision 3: Read from `_BU` (backup/canonical) files, not live runtime files

**Rationale:** Live runtime files (`areas/*.json` without `_BU` suffix, `module_plot.json`) are mutated during gameplay. The adventure document should reflect the authored module, not the current session state. `_BU` files are the canonical shipped content.

**Files read:**
- `module_context_BU.json` (or `module_context.json` if no BU exists)
- `module_plot_BU.json`
- `areas/*_BU.json`
- `monsters/*.json` (static, no runtime variant)
- `map_*_BU.json` (or `map_*.json` if no BU exists)

### Decision 4: Handle The Ancients Lab sparse areas gracefully

**Observation:** The Ancients Lab area `_BU` files have empty descriptions and dmInstructions. The writer handles this by:
- Listing location names and connectivity from area files (this data exists)
- Noting "room descriptions not yet authored" for empty description fields
- Using plot point descriptions as the primary narrative source (these are rich)
- Using NPC descriptions from module_context as character content (these are rich)

### Decision 5: Button placement in Toolkit sidebar

**Rationale:** The user chose sidebar placement. The button appears in the Module Builder page sidebar alongside existing action buttons (Validate, Build, Publish). It should be available only when a module is selected and has passed basic validation (to avoid serving broken documents).

## Architecture

```
modules/<slug>/
  module_context_BU.json ──┐
  module_plot_BU.json ─────┤
  areas/*_BU.json ─────────┤
  monsters/*.json ─────────┤
  map_*_BU.json ───────────┘
         │
         ▼
utils/homebrewery_adventure_writer.py
  ┌──────────────────────────────────┐
  │ generate_homebrewery_adventure() │  ◄── main entry point
  │   ├── _build_cover_page()        │
  │   ├── _build_intro_section()     │
  │   ├── _build_plot_overview()     │
  │   ├── _build_npc_gallery()       │
  │   ├── _build_locations_section() │
  │   ├── _build_monster_appendix()  │
  │   ├── _build_items_appendix()    │
  │   └── _build_credits()           │
  └──────────────────────────────────┘
         │
         ├──► modules/<slug>/MODULE_SUMMARY.md  (file output)
         │
         └──► GET /api/toolkit/modules/<slug>/adventure.md  (HTTP endpoint)
                    │
                    ▼
              web/templates/module_toolkit.html  ([Download Adventure] button)
```

### Writer module structure

```python
# utils/homebrewery_adventure_writer.py

def generate_homebrewery_adventure(module_slug: str) -> str:
    """Return complete Homebrewery V3 markdown for a module."""

def load_module_data(module_slug: str) -> dict:
    """Load all module data sources into a unified dict."""

def _build_cover_page(data: dict) -> str:
    """Build front cover page with title and banner."""

def _build_intro_section(data: dict) -> str:
    """Build introduction page(s) with adventure overview, background, hook."""

def _build_plot_overview(data: dict) -> str:
    """Build plot chain summary with playline framing."""

def _build_npc_gallery(data: dict) -> str:
    """Build NPC entries with descriptions, roles, factions."""

def _build_locations_section(data: dict) -> str:
    """Build location entries with connectivity and map references."""

def _build_monster_appendix(data: dict) -> str:
    """Build monster stat block appendix using homebrewery_style templates."""

def _build_items_appendix(data: dict) -> str:
    """Build items/treasures appendix."""

def _build_credits(data: dict) -> str:
    """Build credits page with author and license attribution.

    Reads from module_context.json:
        data["author"]  -> "Kuhal - Module derived from https://..."
        data["license"] -> "https://creativecommons.org/licenses/by-nc-sa/4.0/"

    Output format uses {{credits}} snippet followed by formatted attribution.
    The author field is parsed to extract a display name and optional source URL.
    The license URL is rendered as a clickable markdown link.
    Includes SRD 5.2.1 attribution line.
    If fields are missing, emits placeholder text.

    Output example:
        \\page
        {{pageNumber,auto}}

        {{credits}}

        ## Credits

        **Author:** Kuhal

        **Source:** [Homebrewery](https://homebrewery.naturalcrit.com/share/SyBdnURLNZ)

        **License:** [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)

        **Module adapted for NeverEndingQuest by the NeverEndingQuest Toolkit.**

        *Portions derived from SRD 5.2.1, CC BY 4.0.*
    """

def _parse_author_field(author_str: str) -> tuple:
    """Parse author field into (display_name, source_url).

    Handles: "Name - Module derived from https://example.com"
             "Name -- description https://example.com"
             "Name" (no URL)
    """
```

### GUI integration

The endpoint returns `Content-Type: text/markdown` with `Content-Disposition: attachment; filename="<slug>_adventure.md"`. The frontend button triggers a download of this file. The user can then paste the content into `https://homebrewery.naturalcrit.com/new`.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Sparse area data produces thin location sections | Plot data and NPC data carry the document. Area sections note missing descriptions explicitly. |
| Monster data may not exist for all referenced creatures | Skip monsters with no `monsters/*.json` file; note in output. |
| Homebrewery V3 snippet API drift | Style templates are versioned with exemplar source dates. If Homebrewery changes, regenerate style definitions. |
| Module data shape varies across modules | Loader function uses safe `.get()` with defaults. Missing keys produce placeholder text, not errors. |
| Large modules may produce documents too big for Homebrewery editor | Homebrewery handles documents up to several hundred KB. For very large modules, consider pagination in a future change. |

## Migration Plan

Not applicable - new capability. The first module to get the treatment is `The_Ancients_Lab`. Other modules can be run through the writer on demand.

## Open Questions

None - all design decisions are resolved above.
