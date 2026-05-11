## 1. Intro Section LLM Rewrite

- [x] 1.1 Add `_llm_intro_narrative(data: dict) -> Optional[str]` helper that calls LLM with the intro prompt, returning the generated markdown or None on failure.
- [x] 1.2 Rewrite `_build_intro_section()` to attempt `_llm_intro_narrative()`, falling back to current deterministic assembly on failure (None returned).
- [x] 1.3 Prepare the LLM prompt in `_llm_intro_narrative()`:
  - Module stats (NPC count, plot count, area count, monster count).
  - Full plot text from all plot points.
  - Author display name.
  - Prompt instructing three `###` sub-sections with specific content.
  - Model: `DM_SUMMARIZATION_MODEL`, temperature=0.5, max_tokens=800.
- [x] 1.4 Remove `_build_plot_abstract()` function — its concatenation fallback is preserved in the intro's LLM fallback path.

**Verification:** Intro section contains `### Module Overview`, `### The Story So Far`, `### Running the Adventure` as LLM-generated headings. Fallback test: when LLM is unavailable, output matches current deterministic format.

## 2. Plot Overview Lead-in LLM Summary

- [x] 2.1 Add `_llm_plot_hook(data: dict) -> Optional[str]` helper that calls LLM with the plot hook prompt, returning a 1-paragraph summary or None on failure.
- [x] 2.2 Update `_build_plot_overview()`:
  - Replace `"The adventure follows a chain of N plot points:"` with `_llm_plot_hook()` result.
  - Fallback: deterministic one-liner like `"The adventure unfolds across N scenes..."`.
  - Model: `DM_SUMMARIZATION_MODEL`, temperature=0.7, max_tokens=250.
- [x] 2.3 Build plot hook prompt: colourful fantasy blurb style, no plot point IDs, third-person present tense.

**Verification:** Plot overview lead-in does NOT contain "The adventure follows a chain of". Fallback test: when LLM unavailable, deterministic one-liner appears.

## 3. Actions Heading H4

- [x] 3.1 Change `> ### Actions` to `> #### Actions` on line 524 of `_build_monster_appendix()`.

**Verification:** Generated stat blocks contain `> #### Actions` not `> ### Actions`.

## 4. Credits Format

- [x] 4.1 Rewrite `_build_credits()` to exact format:
  - `{{credits}}` on its own line.
  - `{{wide` block opening on next line (no blank line after `{{wide`).
  - `# Credits` H1 heading inside wide block.
  - `**Module adapted for NeverEndingQuest**` bold line.
  - `**Module Builder:** [NEQ-TTRPG](https://github.com/zeug-zz/NeverEndingQuest-TTRPG)`.
  - `**Author:** {display_name}` (parsed via `_parse_author_field()`).
  - `**Source:** [{source_url}]({source_url})` as markdown link (URL as display text).
  - `**License:** [{license_url}]({license_url})` as markdown link (URL as display text).
  - `*Portions derived from SRD 5.2.1, CC BY 4.0.*` at bottom.
  - `}}` closing the wide block on its own line.
- [x] 4.2 If no author data, include placeholder in credits.
- [x] 4.3 Remove `_license_link_text()` function.

**Verification:** Credits output matches exact template. (PASS)

## 5. Regenerate Ancients Lab

- [x] 5.1 Run `generate_homebrewery_adventure("The_Ancients_Lab")` and write to `MODULE_SUMMARY.md`.
- [x] 5.2 Verify intro section has narrative prose (not bullet stats). (PASS)
- [x] 5.3 Verify plot overview has colourful lead-in (not "chain of X points"). (PASS)
- [x] 5.4 Verify stat blocks use `> #### Actions`. (PASS)
- [x] 5.5 Verify credits have `{{credits}}` + `{{wide}}` block with NEQ-TTRPG link. (PASS)
- [x] 5.6 Verify SRD attribution in credits. (PASS)

## 6. Test Updates

- [x] 6.1 Update `scripts/test_homebrewery_adventure_writer.py`:
  - Updated `## Credits` to `# Credits`.
  - Updated `Creative Commons License` to `[https://creativecommons.org` URL format.
- [x] 6.2 Run updated test suite — all pass. (PASS - 78/78)

**Verification:** All adventure writer tests pass with updated assertions.

## 7. Final Validation

- [x] 7.1 Run `.venv/bin/python -m py_compile utils/homebrewery_adventure_writer.py`. (PASS)
- [x] 7.2 Run both test suites. (PASS - 78/78)
- [x] 7.3 Run ASCII compliance check on modified Python files. (PASS - 0 new violations)
- [x] 7.4 Run `openspec validate toolkit-homebrewery-adventure-md-narrative-llm`. (PASS)
