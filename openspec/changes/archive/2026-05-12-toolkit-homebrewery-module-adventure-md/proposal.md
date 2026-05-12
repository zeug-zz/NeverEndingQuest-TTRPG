## Why

The NeverEndingQuest Module Builder toolkit produces complete playable modules but has no export path for human-readable adventure documents. The current `MODULE_SUMMARY.md` in modules is a 5-line stub. DM facilitators who want to read the module offline, share it with other DMs, or upload it to the Homebrewery (https://homebrewery.naturalcrit.com) have no way to get a formatted adventure document.

The `The_Ancients_Lab` module has rich narrative content after the Lovecraftian enrichment pass: 9 NPCs with 5-playline interpretations, 13 plot points with descriptions, monster data, and map data. This content is locked inside NEQ JSON files and invisible to human readers.

A Homebrewery V3 adventure markdown generator would make module content accessible for reading, sharing, and Homebrewery upload. The generator should be deterministic, reading only from NEQ module JSON data, and producing a complete Homebrewery brew file.

## What Changes

- Build `utils/homebrewery_adventure_writer.py` - a generator that reads NEQ module data (module_context, module_plot, areas, monsters, maps) and produces a complete Homebrewery V3 adventure markdown document.
- Pilot on `modules/The_Ancients_Lab` - rewrite `MODULE_SUMMARY.md` as a full Homebrewery adventure markdown file.
- Add `[Download Adventure]` button to the Toolkit Module Builder sidebar.
- Add API endpoint: `GET /api/toolkit/modules/<slug>/adventure.md`.
- Add contract tests verifying generated output structure and completeness.

**Generated document structure:**

| Section | Source Data | Content |
|---------|------------|---------|
| Front Cover | module_context | Module title, subtitle, {{banner HOMEBREW}} |
| Introduction | module_context | Adventure overview, background, hook, DM guidance |
| Plot Overview | module_plot_BU | Plot chain summary, playline framing, ending matrix |
| NPC Gallery | module_context.npcs | All NPCs with descriptions, roles, factions |
| Locations | areas + maps | Location entries with map references |
| Monster Gallery | monsters/*.json | Stat blocks in Homebrewery format |
| Appendix A: Treasures | areas (locations lootTable) | Magic items and treasures |
| Credits | module_context | Attribution, SRD notice |

## Capabilities

### New Capabilities

- `toolkit-homebrewery-adventure-md-generator`: Deterministic conversion of NEQ module JSON data to Homebrewery V3 adventure markdown, using templates from `utils/homebrewery_style.py`.
- `toolkit-module-adventure-download`: Toolkit GUI endpoint to serve the adventure markdown file for download or Homebrewery paste.

## Non-Goals

- Do not implement PDF generation (deferred to follow-up change: `toolkit-homebrewery-adventure-pdf`).
- Do not modify NEQ module JSON schema - read-only access.
- Do not merge with the original community adventure file - NEQ data only.
- Do not add runtime dependencies (pure Python stdlib generation, no markdown→HTML→PDF pipeline yet).
- Do not generate legacy renderer format - V3 only.
- Do not handle module data that doesn't follow the expected schema shape (fail with clear error).
- Do not add the download button to the runtime game interface (toolkit only for this change).

## Impact

- **New files:** `utils/homebrewery_adventure_writer.py`, `scripts/test_homebrewery_adventure_writer.py`
- **Modified files:** `web/extensions/toolkit_module_finisher.py` (post-build hook), `web/web_interface.py` (endpoint), `web/templates/module_toolkit.html` (button)
- **Dependencies:** Requires `toolkit-homebrewery-style-definitions` (imports `utils/homebrewery_style.py`).
- **Backward compatibility:** Zero impact on runtime gameplay. Toolkit-only change.
- **SP/MP compatibility:** Not applicable.

## Review Notes

The Ancients Lab area data is rich after the `toolkit-homebrewery-location-enrichment` change: 4 areas with 3 locations each (12 total), full dmInstructions, NPCs, monsters, plot hooks, features, DC checks, and cross-area connectivity. The writer renders all of this deterministically. Section builders with LLM assistance (`_llm_intro_narrative()`, `_llm_plot_hook()`, `_llm_area_overview()`) enhance the prose quality for the introduction, plot overview, and area overviews while keeping deterministic fallbacks for all LLM-reliant sections.
