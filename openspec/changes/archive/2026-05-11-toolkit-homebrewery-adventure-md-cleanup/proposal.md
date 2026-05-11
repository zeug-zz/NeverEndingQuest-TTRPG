## Why

The generated Ancients Lab Homebrewery brew uploaded for live review exposed 8 formatting and data-loading issues that make the output unsuitable for publication. These fall across three defect classes:

**Data loading bugs** — The `load_module_data()` function reads `_BU` files which contain incomplete narrative data (3 of 9 NPCs described, empty author/license). Area files lack `locationName` (the schema uses `areaName`), and both live and BU variants are loaded without deduplication, producing duplicate entries.

**Formatting non-compliance** — The metadata header uses triple-backtick code fence syntax visible in the Homebrewery editor; main sections use `##` (H2) headings when Homebrewery renders `#` (H1) as wide blocks. Monster stat blocks use `> ##` (H2 instead of H3) and actions show only names without attack bonus, damage dice, damage bonus, or damage type.

**Content quality** — The plot overview dumps all 13 plot points raw with no narrative abstract. Six of nine NPCs appear with no description text. Credits show "attribution not available" despite the data existing in the live context file.

## What Changes

### Data Loading Hygiene
- After loading from `_BU` canonical files, merge narrative data (NPC descriptions, roles, factions; plot point descriptions; area descriptions/names) from the live file where BU entries are empty or missing.
- Deduplicate areas by `areaId` after loading — both live and BU filenames currently resolve to the same BU file through `_prefer_bu()`, causing duplicates.
- Read `areaName` as the primary display name field (schema-correct), falling back to `locationName` then `areaId`.

### Format Corrections
- **Metadata header**: Change from `` ```metadata ... ``` `` code fence to HTML comment syntax: `<!--\nmetadata\ntitle: '...'\n...\n-->` — the format recognized by the Homebrewery editor.
- **Section headings**: Change all top-level sections from `## Section` (H2) to `# Section` (H1) to use Homebrewery wide-block layout.
- **Monster stat blocks**: Change name heading from `> ## Name` to `> ### Name` (H3, underlined). Separate special abilities (`> ***Name.*** ...`) from actions (`> ***Action.*** *Melee Weapon Attack:* +N to hit, ...X (YdZ + B) damage.*`).
- **Attack formatting**: Render `attackBonus`, `damageDice`, `damageBonus`, and `damageType` from structured monster action data as 5e-syntax attack lines.

### Content Quality
- **Plot abstract**: Attempt LLM summarization of all plot point descriptions into a 2-3 paragraph narrative abstract. Fail-open: if LLM is unavailable, concatenate opening sentences from PP001 and closing sentences from the final plot point.
- **NPC descriptions**: After merging from live file, all 9 NPCs should have their full Lovecraftian descriptions (400-576 chars each).
- **Credits**: Already fixed in `load_module_data()` — regenerate MODULE_SUMMARY.md to pick up the correct author/license from live `module_context.json`.

## Capabilities

### New Capabilities

- `toolkit-homebrewery-adventure-md-data-hygiene`: The writer SHALL merge narrative-enriched live file data into BU-loaded structures where BU entries are empty, deduplicate areas by `areaId`, and read `areaName` for location display names.

- `toolkit-homebrewery-adventure-md-format-corrections`: The metadata header SHALL use HTML comment syntax; top-level sections SHALL use `# ` (H1); monster stat block names SHALL use `> ### ` (H3); monster actions SHALL include formatted attack/damage lines.

- `toolkit-homebrewery-adventure-md-plot-abstract`: The builder SHALL attempt LLM summarization of all plot point descriptions into a narrative abstract, falling back to deterministic concatenation on failure.

### Modified Capability
- `toolkit-homebrewery-adventure-md-generator` (from parent change): Updated heading level and stat block formatting requirements.

## Non-Goals

- NPC/monster image insertion — deferred until image hosting strategy is decided.
- Page overflow max-line guidance — documentation note only, not code.
- Items appendix population — deferred; gameplay-generated data.
- Plot point individual descriptions — already rich from the Lovecraftian enrichment pass.
- Any changes to NEQ JSON schemas.
- PDF generation (separate follow-up change).

## Impact

- **Affected files:** `utils/homebrewery_style.py`, `utils/homebrewery_adventure_writer.py`, `modules/The_Ancients_Lab/MODULE_SUMMARY.md`, `scripts/test_homebrewery_style_definitions.py`, `scripts/test_homebrewery_adventure_writer.py`
- **Dependencies:** `toolkit-homebrewery-style-definitions` (parent), `utils.ai_client_factory` (for LLM plot abstract)
- **Backward compatibility:** All existing callers continue to work. Format changes affect output appearance only.
- **SP/MP compatibility:** Not applicable (toolkit change only).

## Review Notes

The BU-vs-live merge is the most impactful change — it determines whether enriched narrative content reaches the generated document. The merge strategy is additive: start with BU for canonical structure (NPC list, plot order, area topology), then overlay live file data where BU fields are empty or shorter. This preserves the BU's structural authority while surfacing enrichment.
