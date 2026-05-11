## 1. Exemplar Analysis

- [x] 1.1 Inventory all 33 local Homebrewery files by renderer type (V3 vs legacy) and file size.
- [x] 1.2 Extract V3 metadata header patterns from all 5 V3 brews (fields, values, ordering).
- [x] 1.3 Extract cover page patterns including snippets, heading hierarchy, image placement, banner.
- [x] 1.4 Extract section structure patterns: page breaks, column breaks, heading levels used.
- [x] 1.5 Extract monster stat block patterns: HR separators, blockquote structure, ability tables, action formatting.
- [x] 1.6 Extract item/treasure block patterns.
- [x] 1.7 Extract image placement syntax variants (absolute positioning, image masks, wide images).
- [x] 1.8 Extract table of contents, wide content, and other V3 snippet patterns.
- [x] 1.9 Extract footnote, credits, and back-matter patterns.
- [x] 1.10 Attempt online fetch of Homebrewery docs from `https://homebrewery.naturalcrit.com` (fail-open, returned HTTP 200).

**Verification for 1.1-1.10:** Analysis script outputs structured JSON summary of all extracted patterns. Contract tests verify extraction completeness against known V3 brew structures.

## 2. Python Template Module

- [x] 2.1 Write `utils/homebrewery_style.py` module header with SPDX license and docstring.
- [x] 2.2 Implement metadata template (`METADATA_TEMPLATE`) and `format_metadata()` helper.
- [x] 2.3 Implement cover page template (`COVER_PAGE_TEMPLATE`) and `format_cover_page()` helper.
- [x] 2.4 Implement page break and column break constants (`PAGE_BREAK`, `COLUMN_BREAK`).
- [x] 2.5 Implement monster stat block template (`MONSTER_STATBLOCK_TEMPLATE`) and `format_monster_statblock()` helper.
- [x] 2.6 Implement item block template (`ITEM_BLOCK_TEMPLATE`) and `format_item_block()` helper.
- [x] 2.7 Implement image placement helpers (`format_image_placement()`, `IMAGE_MASK_SNIPPETS`).
- [x] 2.8 Implement table of contents and wide content templates.
- [x] 2.9 Implement footer/credits templates.
- [x] 2.10 Implement `sanitize_markdown_text()` helper for ASCII-safe content.
- [x] 2.11 Write `__all__` export list.

**Verification for 2.1-2.11:** `.venv/bin/python -m py_compile utils/homebrewery_style.py` passes. All template constants are non-empty strings. All helper functions are callable and accept documented parameters.

## 3. Style Reference Document

- [x] 3.1 Write `data/homebrewery_style_reference.md` with quick-start skeleton.
- [x] 3.2 Document each template element from `utils/homebrewery_style.py` with extracted examples.
- [x] 3.3 Include V3-vs-legacy difference callouts.
- [x] 3.4 Include section ordering guidance.
- [x] 3.5 Include known edge cases and quirks observed in exemplars.

**Verification for 3.1-3.5:** Document is valid markdown. Every exported symbol from `utils/homebrewery_style.py` has a corresponding documented section.

## 4. Contract Tests

- [x] 4.1 Write `scripts/test_homebrewery_style_definitions.py` test module.
- [x] 4.2 Test that `utils/homebrewery_style` imports without error.
- [x] 4.3 Test that all template constants are non-empty strings.
- [x] 4.4 Test that `format_metadata()` produces valid YAML header.
- [x] 4.5 Test that `format_cover_page()` produces a page with all required snippets.
- [x] 4.6 Test that `format_monster_statblock()` produces a valid stat block with ability table.
- [x] 4.7 Test that `format_item_block()` produces a valid item block.
- [x] 4.8 Test that `sanitize_markdown_text()` handles non-ASCII characters safely.
- [x] 4.9 Test that no template contains legacy renderer patterns (div-based page numbers, `.phb` CSS classes).

**Verification for 4.1-4.9:** `.venv/bin/python scripts/test_homebrewery_style_definitions.py` passes all tests.

## 5. Final Validation

- [x] 5.1 Run `.venv/bin/python -m py_compile utils/homebrewery_style.py`. (PASS)
- [x] 5.2 Run `.venv/bin/python scripts/test_homebrewery_style_definitions.py`. (PASS - 37/37)
- [x] 5.3 Run ASCII compliance check on new Python files. (PASS - 0 violations in new files)
- [x] 5.4 Run `openspec validate toolkit-homebrewery-style-definitions`. (PASS - valid)
