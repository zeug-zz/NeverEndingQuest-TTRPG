# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Homebrewery V3 Style Templates and Helpers

Provides Python constants and helper functions for generating Homebrewery V3
renderer-compatible markdown documents. Patterns extracted from local exemplars
in Local_Docs/modules/hombrew/.

Usage:
    from utils.homebrewery_style import (
        format_metadata,
        format_cover_page,
        format_monster_statblock,
        format_item_block,
        format_image_placement,
        sanitize_markdown_text,
        PAGE_BREAK,
        COLUMN_BREAK,
    )

    doc = format_metadata("My Adventure")
    doc += format_cover_page("My Adventure", "A 5e Module", "cover.jpg")
    doc += PAGE_BREAK
    doc += "## Introduction\\n\\nAdventure text here..."
"""

import re

# ---------------------------------------------------------------------------
# V3 Metadata
# ---------------------------------------------------------------------------

METADATA_TEMPLATE = """<!--
metadata
title: '{title}'
description: '{description}'
tags: [{tags}]
systems: [{systems}]
renderer: V3
theme: 5ePHB

-->
"""

# ---------------------------------------------------------------------------
# Cover Page
# ---------------------------------------------------------------------------

COVER_PAGE_TEMPLATE = """{front_cover}

# {title}

## {subtitle}

![background image]({cover_image_url}) {{position:absolute,bottom:0,left:0,height:100%}}

{{{{banner HOMEBREW}}}}
"""

FRONT_COVER_SNIPPET = "{{frontCover}}"
BANNER_SNIPPET = "{{banner HOMEBREW}}"
PAGE_NUMBER_SNIPPET = "{{pageNumber,auto}}"
INSIDE_COVER_SNIPPET = "{{insideCover}}"
CREDITS_SNIPPET = "{{credits}}"

# ---------------------------------------------------------------------------
# Page / Column Breaks
# ---------------------------------------------------------------------------

PAGE_BREAK = """\\page

{{pageNumber,auto}}
"""

COLUMN_BREAK = """\\column
"""

# ---------------------------------------------------------------------------
# Image Placement
# ---------------------------------------------------------------------------

IMAGE_PLACEMENT_TEMPLATE = "![{alt}]({url}) {{position:absolute,{position_args}}}"

IMAGE_MASK_EDGE7_TEMPLATE = """{{{{imageMaskEdge7,{mask_args}
  ![]({url}){{width:100%}}
}}}}"""

IMAGE_MASK_SNIPPETS = {
    "edge7": IMAGE_MASK_EDGE7_TEMPLATE,
}
"""Common V3 image mask snippets. Key 'edge7' is the edge feather mask."""

# ---------------------------------------------------------------------------
# Table of Contents
# ---------------------------------------------------------------------------

TOC_TEMPLATE = """{{toc}}
"""

# ---------------------------------------------------------------------------
# Wide Content
# ---------------------------------------------------------------------------

WIDE_CONTENT_TEMPLATE = """{{{{wide

{content}

}}}}
"""

# ---------------------------------------------------------------------------
# Footnotes
# ---------------------------------------------------------------------------

FOOTNOTE_TEMPLATE = "{{{{footnote {text}}}}}"

# ---------------------------------------------------------------------------
# Monster Stat Block
# ---------------------------------------------------------------------------

MONSTER_PORTRAIT_URL = "https://lh3.googleusercontent.com/d/1gZxbtmUB76w8Yf7oku1F6CMdYfFeT0cR"

NPC_PORTRAIT_URL = "https://lh3.googleusercontent.com/d/1gZxbtmUB76w8Yf7oku1F6CMdYfFeT0cR"

COVER_IMAGE_URL = "https://lh3.googleusercontent.com/d/1eiB3SRNY14qSDs4hdBEJoR8MYsC48P3B"

MONSTER_STATBLOCK_TEMPLATE = """___
___
> ### {name}
>![{name}]({portrait_url}){{width:100px,margin-right:0.5cm,wrapRight}}
>___
> {size} {creature_type}, {alignment}
> ___
> **Armor Class** {armor_class}
> ___
> **Hit Points** {hit_points}
> ___
> **Speed** {speed}
> ___
:
>|STR|DEX|CON|INT|WIS|CHA|
>|:---:|:---:|:---:|:---:|:---:|:---:|
>|{str_score} ({str_mod})|{dex_score} ({dex_mod})|{con_score} ({con_mod})|{int_score} ({int_mod})|{wis_score} ({wis_mod})|{cha_score} ({cha_mod})|
>___
{abilities_section}
{actions_section}
"""

# ---------------------------------------------------------------------------
# Item / Treasure Block
# ---------------------------------------------------------------------------

ITEM_BLOCK_TEMPLATE = """---
>#### {name}
>**{rarity}**
>
>{description}
"""

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def format_metadata(
    title: str = "Untitled Adventure",
    description: str = "",
    tags: str = "",
    systems: str = "",
) -> str:
    """Return V3 metadata YAML header block."""
    return METADATA_TEMPLATE.format(
        title=title,
        description=description,
        tags=tags,
        systems=systems,
    )


def format_cover_page(
    title: str,
    subtitle: str = "",
    cover_image_url: str = "",
) -> str:
    """Return V3 cover page with frontCover, title, image, banner, page number.

    Args:
        title: Module title (## heading).
        subtitle: Module subtitle (# heading), shown below title.
        cover_image_url: Background image URL for the cover.

    Returns:
        Complete cover page markdown block.
    """
    return COVER_PAGE_TEMPLATE.format(
        front_cover=FRONT_COVER_SNIPPET,
        title=title,
        subtitle=subtitle,
        cover_image_url=cover_image_url,
    )


def _format_ability_mod(score: int) -> str:
    """Format ability score modifier as signed string."""
    mod = (score - 10) // 2
    if mod >= 0:
        return f"+{mod}"
    return str(mod)


def _format_damage_dice(dice: str, bonus: int, dtype: str, attack_bonus: int) -> str:
    """Format a 5e attack line from structured monster data.

    Returns str like '*Melee Weapon Attack:* +4 to hit, reach 5 ft., one target.
    *Hit:* 6 (2d4 + 2) piercing damage.'
    """
    attack_line = ""
    if attack_bonus is not None:
        attack_line = "*Melee Weapon Attack:* +{} to hit, reach 5 ft., one target. ".format(
            attack_bonus
        )
    damage_line = ""
    if dice and dice != "0":
        avg_damage = _estimate_average_damage(dice, bonus)
        dice_str = dice
        if bonus > 0:
            dice_str += " + {}".format(bonus)
        elif bonus < 0:
            dice_str += " - {}".format(abs(bonus))
        dtype_label = dtype if dtype and dtype != "None" else ""
        damage_line = "*Hit:* {} ({}) {}".format(avg_damage, dice_str, dtype_label).strip()
        if damage_line and not damage_line.endswith("."):
            damage_line += "."
    result = (attack_line + damage_line).strip()
    return result if result else ""


def _estimate_average_damage(dice_str: str, bonus: int) -> int:
    """Estimate average damage from dice expression like '2d4'."""
    import re
    m = re.match(r"(\d+)d(\d+)", dice_str)
    if m:
        num = int(m.group(1))
        sides = int(m.group(2))
        avg = num * (sides + 1) // 2
        return avg + bonus
    bonus_clean = int(bonus) if bonus else 0
    return bonus_clean


def format_monster_statblock(
    name: str = "Unknown Creature",
    size: str = "Medium",
    creature_type: str = "Monstrosity",
    alignment: str = "Unaligned",
    armor_class: int = 10,
    hit_points: str = "10 (1d8+1)",
    speed: str = "30 ft.",
    strength: int = 10,
    dexterity: int = 10,
    constitution: int = 10,
    intelligence: int = 10,
    wisdom: int = 10,
    charisma: int = 10,
    abilities: str = "",
    actions: str = "",
    portrait_url: str = "",
) -> str:
    """Return a Homebrewery V3-formatted monster stat block.

    Args:
        name: Monster name (## heading inside blockquote).
        size: Creature size category (Tiny, Small, Medium, Large, Huge, Gargantuan).
        creature_type: Creature type (Aberration, Beast, Construct, etc.).
        alignment: Alignment string.
        armor_class: AC value.
        hit_points: HP expression like "45 (6d10+12)".
        speed: Speed string like "30 ft., fly 60 ft.".
        strength, dexterity, constitution, intelligence, wisdom, charisma: Ability scores.
        abilities: Additional trait/ability lines (each prefixed >***Name***).
        actions: Action lines (each prefixed >***Action***).

    Returns:
        Complete stat block markdown.
    """
    return MONSTER_STATBLOCK_TEMPLATE.format(
        name=name,
        size=size,
        creature_type=creature_type,
        alignment=alignment,
        armor_class=armor_class,
        hit_points=hit_points,
        speed=speed,
        str_score=strength,
        str_mod=_format_ability_mod(strength),
        dex_score=dexterity,
        dex_mod=_format_ability_mod(dexterity),
        con_score=constitution,
        con_mod=_format_ability_mod(constitution),
        int_score=intelligence,
        int_mod=_format_ability_mod(intelligence),
        wis_score=wisdom,
        wis_mod=_format_ability_mod(wisdom),
        cha_score=charisma,
        cha_mod=_format_ability_mod(charisma),
        abilities_section=abilities if abilities else ">",
        actions_section=actions if actions else ">",
        portrait_url=portrait_url if portrait_url else MONSTER_PORTRAIT_URL,
    )


def format_item_block(name: str, rarity: str = "", description: str = "") -> str:
    """Return a Homebrewery V3-formatted magic item / treasure block.

    Args:
        name: Item name.
        rarity: Rarity string (Common, Uncommon, Rare, Very Rare, Legendary).
        description: Item description text.

    Returns:
        Complete item block markdown.
    """
    return ITEM_BLOCK_TEMPLATE.format(
        name=name,
        rarity=rarity,
        description=description,
    )


def format_image_placement(
    url: str,
    alt: str = "",
    position_args: str = "",
) -> str:
    """Return V3 curly-brace image placement directive.

    Args:
        url: Image URL.
        alt: Alt text.
        position_args: Position arguments like "top:0,left:0,width:100%".

    Returns:
        V3 image placement markdown.
    """
    if not position_args:
        return f"![{alt}]({url})"
    return IMAGE_PLACEMENT_TEMPLATE.format(
        alt=alt,
        url=url,
        position_args=position_args,
    )


def format_image_mask_edge7(url: str, offset: str = "13%", rotation: str = "0") -> str:
    """Return V3 edge7 image mask snippet.

    Args:
        url: Image URL to mask.
        offset: Mask offset (default "13%").
        rotation: Mask rotation degrees (default "0").

    Returns:
        Complete image mask block.
    """
    args = f"--offset:{offset},--rotation:{rotation}"
    return IMAGE_MASK_EDGE7_TEMPLATE.format(url=url, mask_args=args)


def format_toc() -> str:
    """Return V3 table of contents snippet."""
    return TOC_TEMPLATE


def format_wide_content(content: str) -> str:
    """Wrap content in wide layout snippet."""
    return WIDE_CONTENT_TEMPLATE.format(content=content)


def format_footnote(text: str) -> str:
    """Return V3 footnote snippet."""
    return FOOTNOTE_TEMPLATE.format(text=text)


def sanitize_markdown_text(text: str) -> str:
    """Sanitize text for safe inclusion in Homebrewery markdown.

    Replaces non-ASCII characters with ASCII equivalents and escapes
    problematic markdown characters where needed.

    Args:
        text: Raw text that may contain non-ASCII characters.

    Returns:
        ASCII-safe text suitable for inclusion in a Homebrewery document.
    """
    replacements = {
        "\u2014": "--",
        "\u2013": "--",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",
        "\u00e9": "e",
        "\u00e8": "e",
        "\u00ea": "e",
        "\u00e0": "a",
        "\u00e2": "a",
        "\u00f4": "o",
        "\u00f6": "oe",
        "\u00fc": "ue",
        "\u00e4": "ae",
        "\u00eb": "e",
        "\u00ef": "i",
        "\u00ee": "i",
        "\u00f9": "u",
        "\u00fb": "u",
        "\u00e7": "c",
        "\u00b0": " degrees",
        "\u2020": "+",
        "\u2021": "+",
        "\u2122": "(tm)",
        "\u00ae": "(r)",
        "\u00a9": "(c)",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Templates
    "METADATA_TEMPLATE",
    "COVER_PAGE_TEMPLATE",
    "MONSTER_STATBLOCK_TEMPLATE",
    "ITEM_BLOCK_TEMPLATE",
    "MONSTER_PORTRAIT_URL",
    "NPC_PORTRAIT_URL",
    "COVER_IMAGE_URL",
    "IMAGE_PLACEMENT_TEMPLATE",
    "IMAGE_MASK_EDGE7_TEMPLATE",
    "TOC_TEMPLATE",
    "WIDE_CONTENT_TEMPLATE",
    "FOOTNOTE_TEMPLATE",
    # Snippets
    "FRONT_COVER_SNIPPET",
    "BANNER_SNIPPET",
    "PAGE_NUMBER_SNIPPET",
    "INSIDE_COVER_SNIPPET",
    "CREDITS_SNIPPET",
    # Breaks
    "PAGE_BREAK",
    "COLUMN_BREAK",
    # Helpers
    "format_metadata",
    "format_cover_page",
    "format_monster_statblock",
    "format_item_block",
    "format_image_placement",
    "format_image_mask_edge7",
    "format_toc",
    "format_wide_content",
    "format_footnote",
    "sanitize_markdown_text",
    "_format_damage_dice",
    "_estimate_average_damage",
]
