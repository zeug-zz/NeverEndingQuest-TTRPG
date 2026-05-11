# Homebrewery V3 Style Reference

Extracted from 5 V3 exemplars in `Local_Docs/modules/hombrew/`.

---

## Quick Start

Minimal V3 document skeleton:

````markdown
```metadata
title: 'My Adventure'
description: ''
tags: []
systems: []
renderer: V3
theme: 5ePHB

```

{{frontCover}}

## My Adventure

# A 5th-Level Module

![background image](https://example.com/cover.jpg) {position:absolute,bottom:0,left:0,height:100%}

{{banner HOMEBREW}}

{{pageNumber,auto}}

\page

{{pageNumber,auto}}

## Chapter 1: The Beginning

Adventure text here...
````

---

## Section Ordering (Standard Convention)

1. **Metadata header** (first 10 lines)
2. **Cover page** (`{{frontCover}}` block)
3. **Content pages** (intro, chapters, locations)
4. **Appendices** (items, monsters, maps)
5. **Credits** (`{{credits}}` or custom footer)

---

## 1. Metadata Header

**Syntax:** YAML block between triple backticks labeled `metadata`.

**Fields:**
| Field | Required | Value |
|-------|----------|-------|
| `title` | Yes | Adventure title (single-quoted) |
| `renderer` | Yes | `V3` |
| `theme` | Yes | `5ePHB` |
| `description` | No | Short description |
| `tags` | No | YAML array |
| `systems` | No | YAML array |

**Example (Elden Ring):**

```yaml
title: 'Elden Ring D&D: Call of Grace'
description: ''
tags: []
systems: []
renderer: V3
theme: 5ePHB
```

---

## 2. Cover Page

**Snippets used:** `{{frontCover}}`, `{{banner HOMEBREW}}`, `{{pageNumber,auto}}`

**Structure:**
```
{{frontCover}}

## [Module Title]

# [Subtitle]

![background image](url) {position:absolute,bottom:0,left:0,height:100%}

{{banner HOMEBREW}}

{{pageNumber,auto}}
```

**Example (Elden Ring):**
```
{{frontCover}}

## Elden Ring D&D

# Call of Grace

![background image](https://example.com/cover.jpg) {position:absolute,bottom:0,left:0,height:100%}

{{banner HOMEBREW}}

{{pageNumber,auto}}
```

**Example (The Trouble With The Undead):**
```
{{frontCover}}

## }

# `<small>`The Trouble With THE`</small>` `<br>` UNDEAD
```

Note: HTML in headings is allowed. The `{{insideCover}}` snippet can be used for an optional second cover page.

---

## 3. Page Break

**Syntax:** `\page` on its own line, followed by `{{pageNumber,auto}}`.

```
\page

{{pageNumber,auto}}
```

Every major section and appendix starts with this pattern.

---

## 4. Column Break

**Syntax:** `\column` on its own line.

```
\column
```

Used within a page to split content into two columns. Common in introductions and stat block sections.

---

## 5. Image Placement (V3)

**Syntax:** `![alt](url) {position:absolute,key:value,...}`

**Common position keys:** `top`, `bottom`, `left`, `right`, `width`, `height`, `mix-blend-mode`, `transform`

**Example (cover):**
```
![background image](cover.jpg) {position:absolute,bottom:0,left:0,height:100%}
```

**Example (inline art):**
```
![map](map.png) {position:absolute,bottom:100px,left:50px,width:325px,mix-blend-mode:multiply}
```

---

## 6. Image Mask Snippets

Edge7 mask (used by Elden Ring):

```
{{imageMaskEdge7,--offset:13%,--rotation:0
  ![](url){width:100%}
}}
```

---

## 7. Monster Stat Block

**V3 convention** (adapted from legacy; observed in legacy files, V3 uses same convention):

```
___
___
> ## Monster Name
> *Medium monstrosity, unaligned*
> ___
> - **Armor Class** 14 (natural armor)
> - **Hit Points** 45 (6d10+12)
> - **Speed** 30 ft., climb 30 ft.
>___
>|STR|DEX|CON|INT|WIS|CHA|
>|:---:|:---:|:---:|:---:|:---:|:---:|
>|16 (+3)|14 (+2)|13 (+1)|4 (-3)|4 (-3)|3 (-4)|
>___
> ***Trait Name.*** Trait description.
>
> ### Actions
> ***Attack.*** *Melee Weapon Attack:* +5 to hit, reach 5 ft., one target. *Hit:* 7 (1d6+3) damage.
```

**Key rules:**
- Two HR separators (`___`) before the name
- Blockquote (`>`) prefix for all lines
- Ability table is a markdown table inside blockquote (column-aligned)
- Trait names bolded with `***`
- Section headers (`### Actions`) inside the blockquote
- Separator (`>___`) before and after ability table

---

## 8. Item / Treasure Block

**Syntax:**
```
---
>#### Item Name
>**Rarity**
>
>Description text here...
---
```

---

## 9. Table of Contents

**Syntax:** `{{toc}}`

Optionally with parameters: `{{toc,param1:value}}`

Legacy fallback:
```html
<div class='toc'>
- [Chapter 1](#p3)
- [Chapter 2](#p7)
</div>
```

---

## 10. Wide Content

**Syntax:**
```
{{wide

Full-width content here...

}}
```

Legacy fallback:
```html
<div class='wide'>
Full-width content here...
</div>
```

---

## 11. Footnotes

**Syntax:** `{{footnote Chapter 1 | Section Title}}`

Used for page footer text indicating current chapter/section.

---

## 12. Credits

**Syntax:** `{{credits}}`

Creates a centered credits block. Usually on the last page or inside cover.

---

## 13. Watercolor Decorations

**Syntax:** 
```
{{watercolor2,top:130px,left:-180px,width:410px,transform:rotate(30deg),background-color:#dbc899,opacity:70%}}
```

Numbered variants: `watercolor`, `watercolor2`, `watercolor6`, etc. Used for decorative background elements.

---

## 14. Logo

**Syntax:** `{{logo ![](/assets/naturalCritLogoRed.svg)}}`

---

## 15. V3 vs Legacy Differences

| Feature | V3 | Legacy |
|---------|----|--------|
| Page number | `{{pageNumber,auto}}` | `<div class='pageNumber auto'></div>` |
| Cover | `{{frontCover}}` snippet | CSS `.phb#p1{ text-align:center; }` + `:after{ display:none; }` |
| Image placement | `![alt](url) {position:absolute,...}` | `style='position:absolute;...'` |
| Width/column | `\column` + `{{wide ...}}` | Native two-column (smaller page) |
| Content wrapper | `{{wide ...}}` | `<div class='wide'>...</div>` |
| Style blocks | `<style>` optional | `<style>` blocks common for `.phb` classes |
| Snippet system | `{{snippet,params}}` | No snippet system |

---

## Edge Cases and Quirks

- **Empty fields in metadata:** `description: ''` with single quotes around blank values.
- **Missing renderer field:** Some V3 brews omit the explicit `renderer: V3` line but still use V3 snippets. Specifying it ensures correct rendering.
- **HTML in headings:** `<small>`, `<br>`, and other inline HTML works in Homebrewery headings.
- **Stat block alignment:** V3 renders stat blocks slightly differently than legacy (wider column layout). The blockquote convention is identical.
- **Image URLs:** External URLs work. For local images, upload to an image host first.
- **Brew size:** Homebrewery handles documents up to several hundred KB comfortably. Large maps should use external URLs, not embedded base64.

---

*Style reference generated from analysis of 33 local Homebrewery files (5 V3, 28 legacy).*
