# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Homebrewery Style Analysis - Extract V3 formatting conventions from local exemplars.

Scans all local Homebrewery files in Local_Docs/modules/hombrew/, classifies them
by renderer type (V3 vs legacy), and extracts formatting pattern examples for each
V3 element: metadata headers, cover pages, stat blocks, items, images, etc.

Usage:
    .venv/bin/python scripts/analyze_homebrewery_exemplars.py [--json]
    .venv/bin/python scripts/analyze_homebrewery_exemplars.py --report
"""

import json
import os
import re
import sys
from pathlib import Path

HOMEBREW_DIR = Path("Local_Docs/modules/hombrew")
MARKDOWN_EXTS = (".md", ".markdown")


def classify_renderer(content: str) -> str:
    """Determine renderer type from metadata block."""
    meta_match = re.search(r"renderer:\s*(\S+)", content)
    if meta_match:
        return meta_match.group(1).strip()
    if "{{frontCover}}" in content or "{{pageNumber,auto}}" in content:
        return "V3"
    if ".phb#" in content or "pageNumber auto" in content:
        return "legacy"
    return "unknown"


def extract_metadata(content: str) -> dict:
    """Extract YAML metadata header fields."""
    meta = {}
    m = re.search(r"```metadata\s*\n(.*?)```", content, re.DOTALL)
    if not m:
        return meta
    for line in m.group(1).strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip().strip("'\"")
    return meta


def extract_snippets(content: str) -> list:
    """Extract all V3 {{snippet}} usages."""
    return re.findall(r"\{\{(.+?)\}\}", content)


def extract_stat_blocks(content: str) -> list:
    """Extract monster stat blocks (HR + blockquote pattern)."""
    blocks = []
    pattern = re.compile(
        r"^(?:___|---)\s*\n"
        r"(?:___|---)\s*\n"
        r">\s*##\s+(.+?)\n"
        r"(.*?)(?=\n(?:___|---)\s*\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(content):
        name = match.group(1).strip()
        body = match.group(2).strip()
        blocks.append({"name": name, "body_preview": body[:200]})
    return blocks


def extract_cover_page(content: str) -> dict:
    """Extract cover page snippet variables."""
    cover = {}
    if "{{frontCover}}" in content:
        cover["has_frontCover"] = True
    if "{{banner HOMEBREW}}" in content:
        cover["has_banner"] = True
    if "{{pageNumber,auto}}" in content:
        cover["has_pageNumber"] = True
    img_pos = re.findall(
        r"!\[.*?\]\((.*?)\)\s*\{position:absolute,([^}]+)\}", content
    )
    if img_pos:
        cover["cover_images"] = [{"url": u, "position": p} for u, p in img_pos]
    title_match = re.search(r"^## (.+)$", content, re.MULTILINE)
    if title_match:
        cover["title_pattern"] = f"## {title_match.group(1)}"
    subtitle_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    if subtitle_match:
        cover["subtitle_pattern"] = f"# {subtitle_match.group(1)}"
    return cover


def extract_item_blocks(content: str) -> list:
    """Extract magic item / treasure blocks."""
    items = []
    pattern = re.compile(
        r">#### (.+?)\n"
        r">\*\*(.+?)\*\*.*?\n"
        r">\s*\n"
        r"(>.*?(?=\n(?:---|___)|\Z))",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(content):
        items.append(
            {
                "name": match.group(1).strip(),
                "rarity": match.group(2).strip(),
                "body_preview": match.group(3).strip()[:150],
            }
        )
    return items


def analyze_file(filepath: Path) -> dict:
    """Analyze a single Homebrewery markdown file."""
    content = filepath.read_text("utf-8", errors="replace")
    file_size = filepath.stat().st_size
    line_count = content.count("\n") + 1
    renderer = classify_renderer(content)
    metadata = extract_metadata(content)
    snippets = extract_snippets(content)
    stat_blocks = extract_stat_blocks(content)
    cover = extract_cover_page(content)
    items = extract_item_blocks(content)

    has_column = "\\column" in content
    has_page = "\\page" in content
    has_style_block = bool(re.search(r"<style>.*?</style>", content, re.DOTALL))
    has_toc = "{{toc" in content or "toc" in content.lower()

    return {
        "file": filepath.name,
        "relative_path": str(filepath.relative_to(HOMEBREW_DIR)),
        "size_bytes": file_size,
        "line_count": line_count,
        "renderer": renderer,
        "metadata": metadata,
        "snippets": list(set(snippets)),
        "snippet_count": len(set(snippets)),
        "stat_block_count": len(stat_blocks),
        "item_block_count": len(items),
        "has_column_break": has_column,
        "has_page_break": has_page,
        "has_style_block": has_style_block,
        "has_toc": has_toc,
        "cover": cover,
        "stat_blocks": stat_blocks[:3],
        "items": items[:3],
    }


def scan_all() -> list:
    """Scan all markdown files in the homebrew directory."""
    results = []
    if not HOMEBREW_DIR.exists():
        return results
    for f in sorted(HOMEBREW_DIR.rglob("*")):
        if f.suffix.lower() in MARKDOWN_EXTS:
            results.append(analyze_file(f))
    return results


def build_summary(results: list) -> dict:
    """Build summary statistics from scan results."""
    v3 = [r for r in results if r["renderer"] == "V3"]
    legacy = [r for r in results if r["renderer"] == "legacy"]

    # Collect all V3 snippets
    all_v3_snippets = set()
    for r in v3:
        all_v3_snippets.update(r["snippets"])

    return {
        "total_files": len(results),
        "v3_count": len(v3),
        "legacy_count": len(legacy),
        "unknown_count": len(results) - len(v3) - len(legacy),
        "total_size_bytes": sum(r["size_bytes"] for r in results),
        "largest_v3": sorted(v3, key=lambda r: r["size_bytes"], reverse=True)[:3],
        "all_v3_snippets": sorted(all_v3_snippets),
        "v3_stat_block_total": sum(r["stat_block_count"] for r in v3),
        "v3_item_block_total": sum(r["item_block_count"] for r in v3),
        "v3_have_cover": sum(1 for r in v3 if r["cover"].get("has_frontCover")),
        "v3_have_column": sum(1 for r in v3 if r["has_column_break"]),
        "v3_have_toc": sum(1 for r in v3 if r["has_toc"]),
    }


def print_summary(summary: dict):
    """Print human-readable summary."""
    print("=" * 60)
    print("Homebrewery Exemplar Analysis Summary")
    print("=" * 60)
    print(f"Total files:     {summary['total_files']}")
    print(f"  V3 renderer:   {summary['v3_count']}")
    print(f"  Legacy:         {summary['legacy_count']}")
    print(f"  Unknown:        {summary['unknown_count']}")
    print(f"Total size:      {summary['total_size_bytes'] / 1024:.0f} KB")
    print()
    print(f"V3 Stat blocks:  {summary['v3_stat_block_total']}")
    print(f"V3 Item blocks:  {summary['v3_item_block_total']}")
    print(f"V3 Covers:       {summary['v3_have_cover']}/{summary['v3_count']}")
    print(f"V3 Column breaks:{summary['v3_have_column']}/{summary['v3_count']}")
    print(f"V3 TOC:          {summary['v3_have_toc']}/{summary['v3_count']}")
    print()
    print("V3 Snippets found:")
    for s in summary["all_v3_snippets"]:
        print(f"  {{{{${s.strip()}${s.strip()}}}}}")
    print()
    if summary["largest_v3"]:
        print("Largest V3 files:")
        for r in summary["largest_v3"]:
            print(f"  {r['relative_path']} ({r['size_bytes'] / 1024:.0f} KB, {r['line_count']} lines)")


def main():
    results = scan_all()
    summary = build_summary(results)

    if "--json" in sys.argv:
        print(json.dumps(summary, indent=2))
        return

    if "--report" in sys.argv:
        print_summary(summary)
        print()
        print("Full analysis:")
        print(json.dumps(results, indent=2))
        return

    print_summary(summary)
    print()
    print("Use --json for machine-readable output.")
    print("Use --report for per-file analysis.")


if __name__ == "__main__":
    main()
