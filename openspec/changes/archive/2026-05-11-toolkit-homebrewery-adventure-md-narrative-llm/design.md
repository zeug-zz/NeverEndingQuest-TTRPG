## Context

The `_build_intro_section()` function currently assembles the intro page deterministically: a bullet summary of module stats, a plot abstract (already LLM with fallback), an author line, and a running-the-adventure paragraph. The output reads like an inventory. The user wants narrative flow — colourful fantasy prose that invites a DM to read on.

The `_build_plot_overview()` lead-in line "The adventure follows a chain of N plot points:" is similarly mechanical. A colourful narrative hook would serve the same structural purpose (introducing the plot section) while being more engaging.

Two smaller issues round out this change: actions sub-headings at H3 instead of H4, and credits needing a `{{wide}}` block for visual coherence.

## Goals / Non-Goals

**Goals:**
- Replace deterministic intro assembly with LLM-generated narrative prose.
- Replace dry plot overview lead-in with LLM-generated fantasy hook.
- Fix actions heading to H4.
- Reformat credits to `{{credits}}` + `{{wide}}` block with NEQ-TTRPG attribution.
- Preserve current behavior as fallback when LLM is unavailable.

**Non-Goals:**
- No structural changes to the document (page count, section order, heading hierarchy).
- No changes to individual plot point listings.
- No image or media handling.

## Decisions

### Decision 1: Two separate LLM calls for intro and plot lead-in

**Rationale:** Each call has a focused prompt and bounded output. Independent fallback — if the plot overview call fails, the intro still gets LLM treatment, and vice versa. Simpler prompt design than a combined call that would need output parsing.

**Cost:** ~$0.002 per generation (two calls × ~1,200 total tokens). Acceptable for an explicit user action (adventure download button press).

**Fallback per call:**
- Intro: Revert to current deterministic `_build_intro_section()` behavior.
- Plot lead-in: Use a one-line deterministic text like *"The adventure unfolds across thirteen scenes..."*

### Decision 2: Keep `{{credits}}` snippet combined with `{{wide}}`

**Rationale:** `{{credits}}` applies Homebrewery V3 centered-text styling. `{{wide}}` provides full-width layout for the content block. Both are needed for the intended visual treatment. The `{{credits}}` snippet comes first, followed by the `{{wide}}` block on the next line.

### Decision 3: Absorb `_build_plot_abstract()` into the intro LLM call

**Rationale:** The current `_build_plot_abstract()` was a separate function that attempted LLM summarization with concatenation fallback. The intro LLM call now handles the same job (plot summary within the "The Story So Far" section) as part of a larger prompt. The standalone function is removed. If the intro LLM call fails, the old deterministic behavior (including the concatenation fallback) is preserved.

### Decision 4: Keep SRD attribution line in credits

**Rationale:** Legal completeness for SRD-derived content. The line `*Portions derived from SRD 5.2.1, CC BY 4.0.*` is added at the bottom of the `{{wide}}` block.

## Architecture

```
_build_intro_section(data)
  ├── [TRY] _llm_intro_narrative(npc_count, plot_count, ..., full_plot_text, author)
  │     ├── Prompt: "Write three markdown sections..."
  │     ├── Model: DM_SUMMARIZATION_MODEL, temp=0.5, max_tokens=800
  │     └── Returns: markdown with ### Module Overview, ### The Story So Far, ### Running
  │
  └── [FALLBACK] Current deterministic assembly (bullet stats + concatenated abstract + author + running text)

_build_plot_overview(data)
  ├── [TRY] _llm_plot_hook(plot_text)
  │     ├── Prompt: "Write a 1-paragraph colourful fantasy summary..."
  │     ├── Model: DM_SUMMARIZATION_MODEL, temp=0.7, max_tokens=250
  │     └── Returns: markdown paragraph
  │
  └── [FALLBACK] "The adventure unfolds across {N} scenes..." one-liner

_build_monster_appendix(data)
  └── [FIX] "> ### Actions" → "> #### Actions"

_build_credits(data)
  └── [FIX] Format: {{credits}}\n\n{{wide\n...\n}}
```

### Removed functions
- `_build_plot_abstract()` — absorbed into intro LLM call / fallback
- `_license_link_text()` — no longer needed (URLs used as their own display text: `[URL](URL)`)

### Credits format (exact output)

```
{{credits}}

{{wide
# Credits
**Module adapted for NeverEndingQuest**

**Module Builder:** [NEQ-TTRPG](https://github.com/zeug-zz/NeverEndingQuest-TTRPG)

**Author:** {display_name}

**Source:** [{source_url}]({source_url})

**License:** [{license_url}]({license_url})

*Portions derived from SRD 5.2.1, CC BY 4.0.*
}}
```

Where `{display_name}` and `{source_url}` come from `_parse_author_field(author_raw)`. License URL is used as both display text and href (`[URL](URL)`). The `_license_link_text()` helper is removed.

### LLM prompt templates

**Intro narrative prompt:**
```
You are writing a D&D 5e adventure module introduction for a Dungeon Master.
Using the data below, write three markdown sections in colourful fantasy prose:

### Module Overview
A 1-paragraph overview describing what this adventure contains and the opening
situation. Mention the module has {npc_count} NPCs, {plot_count} plot points,
{area_count} locations, and {monster_count} creature stat blocks in flowing
prose (not as a bullet list).

### The Story So Far
A 2-3 paragraph narrative summary of the adventure's plot arc. Cover the overall
journey, key locations, and central conflict. Write in third-person present tense.
Do NOT list individual plot point IDs.

### Running the Adventure
A 1-paragraph practical note about party size, level range, and DM preparation.

DATA:
Author: {author_name}
Level range: 3-5

PLOT TEXT:
{full_plot_text}
```

**Plot hook prompt:**
```
Write a 1-paragraph colourful fantasy summary introducing the adventure plot chain
below. Write like the opening of a story or the back-cover blurb of a novel.
Capture the central mystery and tone. Do not list plot point IDs. Use third-person
present tense.

PLOT TEXT:
{plot_text}
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| LLM generates markdown with syntax errors | Fallback preserves current correct output. LLM output is passed through `sanitize_markdown_text()`. |
| LLM generates content that conflicts with module data | Prompt constrains LLM to use only the provided data. Temperature is moderate (0.5 intro, 0.7 hook). |
| Two LLM calls double cost | Only ~$0.002 per generation. Only invoked during explicit adventure download, not during gameplay. |
| LLM output produces too many tokens | `max_tokens` caps at 800 (intro) and 250 (hook). |

## Files Modified

| File | Change |
|------|--------|
| `utils/homebrewery_adventure_writer.py` | `_build_intro_section()` rewritten with LLM + fallback, `_build_plot_overview()` lead-in replaced, `_build_monster_appendix()` H4 fix, `_build_credits()` reformatted. Remove `_build_plot_abstract()` and `_license_link_text()`. |
| `modules/The_Ancients_Lab/MODULE_SUMMARY.md` | Regenerated |
| `scripts/test_homebrewery_adventure_writer.py` | Updated assertions for new intro/credits format, H4 actions |
