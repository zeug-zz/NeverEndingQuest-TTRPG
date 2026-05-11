## Why

The deterministic adventure markdown builder produces structurally correct but mechanically-written prose. The intro section reads as a bullet-list inventory ("This module contains: 9 named NPCs, 13 plot points...") rather than immersive adventure text. The plot overview lead-in is a dry technical line ("The adventure follows a chain of 13 plot points:"). And two minor formatting issues persist: action sub-headings use H3 instead of H4, and the credits section lacks the Homebrewery `{{wide}}` layout that makes it visually coherent.

These four issues are all localized fixes in the adventure writer module. The two narrative improvements use LLM generation with deterministic fallback to the current behavior on failure — zero regression risk.

## What Changes

### 1. Intro section LLM rewrite
Replace the deterministic `_build_intro_section()` assembly (bullet stats + plot abstract + author + running-text) with an LLM call that produces flowing narrative markdown. The LLM receives module stats, full plot text, author name, and level range. Output is three `###` sub-sections: Module Overview, The Story So Far, Running the Adventure.

**Fallback:** If the LLM fails, the current deterministic behavior is preserved exactly.

### 2. Plot overview lead-in LLM summary
Replace the line `"The adventure follows a chain of N plot points:"` with an LLM-generated colourful fantasy hook paragraph. The LLM receives plot point titles and descriptions. Output is a 1-paragraph narrative lead-in.

**Fallback:** If the LLM fails, use a one-line deterministic summary like *"The adventure unfolds across thirteen scenes, from the windswept Blackcrag Marches to the sunken heart of the Ancients Lab."*

### 3. Actions heading H4
Change `> ### Actions` to `> #### Actions` in the monster stat block appendix. One-character fix.

### 4. Credits format
Rewrite `_build_credits()` to use:
- `{{credits}}` snippet (V3 visual treatment)
- `{{wide}}` block wrapper
- `# Credits` H1 heading
- NEQ-TTRPG GitHub link as Module Builder attribution
- Author, Source, and license as raw URLs
- SRD 5.2.1 attribution line at bottom

## Capabilities

### New Capability
- `toolkit-homebrewery-adventure-md-llm-narrative`: The intro section and plot overview lead-in SHALL be generated via LLM calls with deterministic fallback on failure.

### Modified Capabilities
- `toolkit-homebrewery-adventure-md-format-corrections`: Actions heading level changed from H3 to H4.
- `toolkit-homebrewery-adventure-md-generator`: Credits format changed to `{{credits}}` + `{{wide}}` block with NEQ-TTRPG attribution.

## Non-Goals
- No changes to individual plot point content (PP001-PP013 remain as-is)
- No changes to NPC gallery, locations section, monster stat blocks (except H4)
- No image handling
- No PDF generation
- No schema changes
- No changes to the metadata header, cover page, or section heading structure

## Impact
- **Affected files:** `utils/homebrewery_adventure_writer.py` (4 function edits), `modules/The_Ancients_Lab/MODULE_SUMMARY.md` (regenerated), `scripts/test_homebrewery_adventure_writer.py` (updated assertions)
- **Dependencies:** `utils.ai_client_factory`, `model_config.DM_SUMMARIZATION_MODEL` (already imported)
- **Cost:** ~$0.002 per generation (two LLM calls), fail-open/zero-cost on failure
- **Backward compatibility:** Fallback behavior preserves current deterministic output exactly

## Review Notes
The two LLM calls are independent — each has its own try/except with separate fallback. The intro call uses temperature 0.5 for creative but coherent prose. The plot lead-in uses temperature 0.7 for hook-style flair. Both are bounded to short outputs (800 and 250 tokens respectively).
