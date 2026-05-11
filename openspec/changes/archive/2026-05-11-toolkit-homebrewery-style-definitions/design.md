## Context

Homebrewery (https://homebrewery.naturalcrit.com) is a web-based tool for creating D&D-style homebrew documents. It uses a custom markdown dialect with two renderer generations:

- **Legacy renderer** (`renderer: legacy`): Uses `<style>` blocks with CSS classes like `.phb#p1`, `<div class='pageNumber auto'>`, bare `<img>` tags with inline styles, and `___` horizontal rules for stat block separators. This is the original format used by GM Binder exports.
- **V3 renderer** (`renderer: V3`): Uses `{{snippets}}` for reusable components (`{{frontCover}}`, `{{banner HOMEBREW}}`, `{{pageNumber,auto}}`, `{{imageMaskEdge7,...}}`, `{{toc,...}}`, `{{wide ...}}`), curly-brace syntax for image placement (`{position:absolute,bottom:0,left:0,height:100%}`), and `<style>` blocks scoped to `.page` selectors.

This change targets V3 because:
1. It is the actively maintained renderer by Homebrewery maintainers.
2. The 7 local V3 exemplars are the largest and most polished adventures (Elden Ring, March Across Haleroth, Hostis Humani Generis, etc.).
3. V3 snippets reduce template complexity - a `{{frontCover}}` snippet replaces 10+ lines of legacy CSS/HTML.
4. Homebrewery's online editor defaults to V3 for new brews.

## Goals / Non-Goals

**Goals:**
- Extract the complete V3 formatting vocabulary from local exemplars.
- Produce reusable Python templates for every Homebrewery document section.
- Document conventions with extracted examples.
- Fail-open on online fetch (local exemplars are the primary source).

**Non-Goals:**
- No legacy renderer template extraction (V3 only).
- No Homebrewery markdown parser (templates, not parsing).
- No adventure content generation (separate change).

## Decisions

### Decision 1: Primary source is local exemplars, not online docs

**Rationale:** The Homebrewery site returned HTTP 406 on direct fetch. Even if the homepage is accessible, the local exemplars are more valuable because they demonstrate real-world usage patterns rather than abstract syntax reference. The 7 V3 brews cover all major formatting features.

**Trade-off:** We may miss edge cases documented online but unused in local files. Mitigated by fail-open attempt to fetch online docs.

### Decision 2: Python template constants, not a template engine

**Rationale:** The Homebrewery format is simple enough that string templates with `str.format()` placeholders suffice. A full template engine (Jinja2, etc.) would add a dependency and complexity without benefit for this use case.

**Format:**
```python
HOMEBREWERY_COVER_PAGE = """{{{{frontCover}}}}

## {title}
# {subtitle}

![background image]({cover_image_url}) {{{position_style}}}

{{{{banner HOMEBREW}}}}
{{{{pageNumber,auto}}}}
"""
```

### Decision 3: Style module split into constants + helpers

**Structure:**
```
utils/homebrewery_style.py
  ├── Constants (templates, CSS snippets, snippet signatures)
  │   ├── METADATA_TEMPLATE
  │   ├── COVER_PAGE_TEMPLATE
  │   ├── PAGE_BREAK
  │   ├── COLUMN_BREAK
  │   ├── MONSTER_STATBLOCK_TEMPLATE
  │   ├── ITEM_BLOCK_TEMPLATE
  │   ├── WIDE_CONTENT_WRAPPER
  │   ├── TABLE_OF_CONTENTS_TEMPLATE
  │   ├── IMAGE_MASK_SNIPPETS (edge7, edge8, etc.)
  │   └── FOOTER_TEMPLATES
  └── Helpers
      ├── format_metadata(title, description, tags) -> str
      ├── format_cover_page(title, subtitle, image_url) -> str
      ├── format_monster_statblock(data) -> str
      ├── format_item_block(data) -> str
      ├── format_image_placement(url, position_args) -> str
      ├── format_snippet(snippet_name, kwargs) -> str
      └── sanitize_markdown_text(text) -> str
```

### Decision 4: Style reference document format

The `data/homebrewery_style_reference.md` document uses a convention-reference format:
- Each section documents one Homebrewery element (cover page, stat block, etc.)
- Shows V3 snippet signature and parameters
- Shows extracted example from local exemplars
- Notes quirks and edge cases observed

## Architecture

```
Local_Docs/modules/hombrew/  (33 exemplar files)
    │
    ▼
scripts/test_homebrewery_style_definitions.py  (verification)
    │
    ▼
utils/homebrewery_style.py  (Python templates + helpers)
    │
    ▼
data/homebrewery_style_reference.md  (human reference)
```

The `utils/homebrewery_style.py` module is the canonical programmatic interface. The `data/homebrewery_style_reference.md` is the human-readable companion. Future tools (adventure writer, PDF generator) import from `utils/homebrewery_style.py`.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Homebrewery V3 snippet API could change | Templates are additive; new snippets can be added without breaking existing ones. Snippets are documented with the exemplar version they were observed in. |
| Local exemplars may use undocumented snippet parameters | Parameters not observed in any exemplar are noted as "unverified" in the style reference. Only verified patterns are used by the adventure writer. |
| Legacy-vs-V3 confusion | Legacy templates are explicitly excluded from this module. If legacy support is needed later, a separate `homebrewery_style_legacy.py` module should be created. |
| ASCII compliance | All templates use ASCII-only text. Image URLs and user-provided content may contain non-ASCII characters; the `sanitize_markdown_text()` helper handles this. |

## Migration Plan

Not applicable - this is a new module with no existing consumers to migrate. The adventure writer change (`toolkit-homebrewery-module-adventure-md`) will be the first consumer.

## Open Questions

None - the source material (33 local exemplars) is sufficient to derive all needed V3 conventions.
