## Why

The repository contains 33 Homebrewery adventure brews in `Local_Docs/modules/hombrew/` but has no canonical style reference for the Homebrewery V3 format. The Module Builder toolkit needs to generate Homebrewery-compatible adventure markdown for download and upload to `https://homebrewery.naturalcrit.com`. Before any generation can occur, the Homebrewery formatting vocabulary must be extracted from local exemplars and written as a reusable style definition artifact.

The 33 local files split across two renderer generations: 7 use V3 (newer `{{snippets}}` syntax, curly-brace image placement), 27 use legacy (inline CSS, `class='pageNumber'` divs). The V3 renderer is the target output format because it is better maintained by Homebrewery and is used by the largest, most polished exemplars (Elden Ring, March Across Haleroth, Trouble With The Undead).

## What Changes

- Analyze all 33 local Homebrewery `.md` files in `Local_Docs/modules/hombrew/` to extract V3 formatting patterns: metadata headers, cover pages, page breaks, section headings, column layout, image placement, monster stat blocks, item blocks, tables of contents, wide content, appendices, footnotes, and credits.
- Write `utils/homebrewery_style.py` containing Python constant templates and helper functions for the full V3 vocabulary.
- Write `data/homebrewery_style_reference.md` as a human-readable style guide with examples from local exemplars.
- Attempt to fetch the Homebrewery format reference from `https://homebrewery.naturalcrit.com`; fail-open if unavailable (local exemplars are sufficient).
- Add contract tests verifying all required template functions exist and produce valid V3 markdown fragments.

## Capabilities

### New Capabilities

- `toolkit-homebrewery-style-extraction`: Deterministic extraction of V3 Homebrewery formatting conventions from local exemplar files, producing Python template constants and helper functions.
- `toolkit-homebrewery-style-reference`: Canonical human-readable style guide artifact documenting all V3 Homebrewery conventions with examples.

## Non-Goals

- Do not create runtime game engine code (toolkit/authoring only).
- Do not modify existing NEQ module data.
- Do not implement PDF generation in this change.
- Do not generate any adventure content - style definitions only.
- Do not write a general-purpose markdown parser for Homebrewery files - analysis scripts may read files but the output is templates, not a parser.

## Impact

- **New files:** `utils/homebrewery_style.py`, `data/homebrewery_style_reference.md`, `scripts/test_homebrewery_style_definitions.py`
- **Dependencies:** None - pure Python stdlib, no new packages required.
- **Backward compatibility:** Zero impact on runtime or existing toolkits. Additive-only.
- **SP/MP compatibility:** Not applicable (toolkit change only).

## Review Notes

The 33 local exemplars are comprehensive enough to derive V3 conventions without online access. The largest V3 brews (Elden Ring at 269 KB/3159 lines, March Across Haleroth at 116 KB/2511 lines) contain virtually every V3 formatting feature. The Homebrewery site may return 406 (observed for user profile pages) so online fetch must be fail-open.
