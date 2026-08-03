# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Monster Reference Closure
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

"""
Monster Reference Closure - Standalone module-level functions extracted from
ModuleGenerator for reuse by accurate-ingest ModuleBuilder and other callers.

Provides deterministic collection, materialization, and reporting of
monster references from module area files.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Set

from utils.file_operations import safe_write_json
from utils.enhanced_logger import info, warning, error


# Heuristic patterns that suggest a monster name is a named NPC-like entity
# rather than a generic creature type.
_NPC_TITLE_PATTERNS = [
    "mr", "mrs", "ms", "dr", "lord", "lady", "sir", "dame",
    "master", "mistress",
]


# Creature-type suffixes that, when present, indicate the name is a
# generic creature type even if it otherwise looks like a proper noun.
_CREATURE_TYPE_KEYWORDS = [
    "skeleton", "zombie", "goblin", "bandit", "orc", "ogre",
    "troll", "wight", "ghoul", "ghost", "specter", "spectre",
    "wraith", "shadow", "demon", "devil", "angel", "dragon",
    "wyrm", "wyvern", "griffin", "gryphon", "harpy", "siren",
    "naga", "basilisk", "chimera", "manticore", "golem",
    "elemental", "vampire", "werewolf", "lycanthrope", "fiend",
    "fiendish", "aberrant", "aberration", "beast", "construct",
    "humanoid", "monstrosity", "plant", "swarm", "undead",
    "knight", "guard", "soldier", "warrior", "mage", "wizard",
    "cultist", "priest", "acolyte", "thug", "assassin",
    "scout", "spy", "veteran", "noble", "commoner", "bandit",
    "druid", "berserker", "gladiator", "champion",
]


def normalize_monster_name(name: str) -> str:
    """Normalize monster name to slug format matching validator contract.

    Args:
        name: The raw monster name to normalize.

    Returns:
        Lowercased slug with underscores, containing only alphanumeric
        characters and underscores.
    """
    if not name:
        return ""
    slug = name.lower().strip()
    slug = slug.replace("'", "").replace('"', "")
    slug = slug.replace(" ", "_").replace("-", "_")
    slug = ''.join(c for c in slug if c.isalnum() or c == '_')
    return slug


def get_active_area_files(module_dir: str) -> List[str]:
    """Get list of active area files, excluding backups and temp files.

    Args:
        module_dir: Path to the module directory.

    Returns:
        List of full paths to active area JSON files.
    """
    areas_dir = os.path.join(module_dir, "areas")
    if not os.path.exists(areas_dir):
        return []

    exclude_patterns = ('_BU.json', '.bak', '.backup', '.tmp', '_backup.json')
    area_files = []

    for f in os.listdir(areas_dir):
        if f.endswith('.json') and not any(pattern in f for pattern in exclude_patterns):
            area_files.append(os.path.join(areas_dir, f))

    return area_files


def collect_referenced_monsters(module_dir: str) -> Dict[str, Dict]:
    """Collect all monster references from area files with source context.

    Scans all active area files for monster references in location.monsters[]
    arrays. Returns a dict keyed by normalized slug.

    Args:
        module_dir: Path to the module directory.

    Returns:
        Dict mapping normalized slug to dict with:
            - original_names: list of original name strings
            - sources: list of dicts with area/location context
    """
    referenced: Dict[str, Dict] = {}
    area_files = get_active_area_files(module_dir)

    for area_path in area_files:
        try:
            with open(area_path, 'r') as f:
                area_data = json.load(f)

            area_name = area_data.get("areaName", os.path.basename(area_path))
            area_id = area_data.get("areaId", "unknown")

            for location in area_data.get("locations", []):
                location_name = (
                    location.get("locationName")
                    or location.get("name")
                    or location.get("locationId", "Unknown Location")
                )
                location_id = location.get("locationId", "unknown")

                for monster in location.get("monsters", []):
                    if isinstance(monster, dict):
                        monster_name = monster.get("name", "").strip()
                    else:
                        monster_name = str(monster).strip()

                    if monster_name:
                        slug = normalize_monster_name(monster_name)
                        if slug:
                            if slug not in referenced:
                                referenced[slug] = {
                                    "original_names": set(),
                                    "sources": [],
                                }
                            referenced[slug]["original_names"].add(monster_name)
                            referenced[slug]["sources"].append({
                                "area_id": area_id,
                                "area_name": area_name,
                                "location_id": location_id,
                                "location_name": location_name,
                            })
        except (IOError, json.JSONDecodeError) as e:
            warning(f"Could not read area file {area_path}: {e}", category="module_generation")

    # Convert sets to lists for JSON serialization
    for slug in referenced:
        referenced[slug]["original_names"] = list(referenced[slug]["original_names"])

    return referenced


def collect_existing_monster_slugs(module_dir: str) -> Set[str]:
    """Collect existing monster file slugs from module monsters directory.

    Args:
        module_dir: Path to the module directory.

    Returns:
        Set of lowercased slugs derived from existing monster JSON filenames.
    """
    monsters_dir = os.path.join(module_dir, "monsters")
    if not os.path.exists(monsters_dir):
        return set()

    exclude_patterns = ('_BU.json', '.bak', '.backup', '.tmp', '_backup.json', '.gitkeep')
    slugs: Set[str] = set()

    for f in os.listdir(monsters_dir):
        if f.endswith('.json') and not any(pattern in f for pattern in exclude_patterns):
            slug = f[:-5].lower()
            slugs.add(slug)

    return slugs


def _is_npc_like_name(name: str) -> bool:
    """Check if a monster name appears to be an NPC-like proper noun.

    Uses heuristics: title prefixes (Sir, Lady, etc.) and proper-noun
    patterns without creature-type keywords.

    Args:
        name: The display name to check.

    Returns:
        True if the name resembles an NPC rather than a creature type.
    """
    name_lower = name.lower().strip()

    # Check for NPC title prefixes (case-insensitive, word-boundary)
    first_word = name_lower.split()[0] if name_lower.split() else ""
    if first_word in _NPC_TITLE_PATTERNS:
        return True

    # Check if the name contains any creature-type keyword
    for keyword in _CREATURE_TYPE_KEYWORDS:
        if keyword in name_lower:
            return False

    # Single-word capitalized name with no creature keyword: likely proper noun
    if len(name_lower.split()) == 1 and name_lower[0].isalpha():
        return True

    return False


def _is_ambiguous_npc_like(display_name: str, slug: str) -> bool:
    """Determine whether a monster reference is NPC-like and should be flagged.

    Args:
        display_name: The original display name of the monster.
        slug: The normalized slug.

    Returns:
        True if the name is likely an NPC rather than a generic creature.
    """
    return _is_npc_like_name(display_name)


def materialize_missing_monsters(
    module_name: str,
    module_dir: str,
    missing: Dict[str, Dict],
) -> Dict[str, Any]:
    """Generate missing monster stat files via monster_builder subprocess.

    Args:
        module_name: Name of the module.
        module_dir: Path to the module directory.
        missing: Dict of slug -> info for missing monsters.

    Returns:
        Dict with:
            - generated: list of successful generation records
            - failed: list of failed generation records
            - skipped: list of skipped generation records
    """
    results: Dict[str, Any] = {
        "generated": [],
        "failed": [],
        "skipped": [],
    }

    if not missing:
        return results

    current_dir = os.path.dirname(os.path.abspath(__file__))
    monster_builder_path = os.path.join(current_dir, "..", "core", "generators", "monster_builder.py")

    for slug, monster_info in missing.items():
        display_name = (
            monster_info["original_names"][0]
            if monster_info.get("original_names")
            else slug
        )

        info(f"Generating missing monster: {display_name} ({slug})", category="module_generation")

        try:
            result = subprocess.run(
                [sys.executable, monster_builder_path, display_name, "--module", module_name],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                expected_path = os.path.join(module_dir, "monsters", f"{slug}.json")
                if os.path.exists(expected_path):
                    results["generated"].append({
                        "slug": slug,
                        "display_name": display_name,
                        "path": expected_path,
                    })
                    info(f"Successfully generated monster: {display_name}", category="module_generation")
                else:
                    # Builder may use different slug format -- scan for a match
                    monsters_dir = os.path.join(module_dir, "monsters")
                    found = False
                    for f in os.listdir(monsters_dir):
                        if f.endswith('.json') and not any(p in f for p in ['_BU', '.bak', '.tmp']):
                            if normalize_monster_name(f[:-5]) == slug:
                                results["generated"].append({
                                    "slug": slug,
                                    "display_name": display_name,
                                    "path": os.path.join(monsters_dir, f),
                                })
                                found = True
                                break

                    if not found:
                        results["failed"].append({
                            "slug": slug,
                            "display_name": display_name,
                            "reason": "File not created by builder",
                        })
                        error(
                            f"Monster builder succeeded but file not found for: {display_name}",
                            category="module_generation",
                        )
            else:
                results["failed"].append({
                    "slug": slug,
                    "display_name": display_name,
                    "reason": result.stderr or "Unknown error",
                })
                error(
                    f"Monster builder failed for {display_name}: {result.stderr}",
                    category="module_generation",
                )

        except subprocess.TimeoutExpired:
            results["failed"].append({
                "slug": slug,
                "display_name": display_name,
                "reason": "Timeout after 120 seconds",
            })
            error(f"Monster builder timeout for: {display_name}", category="module_generation")
        except Exception as e:
            results["failed"].append({
                "slug": slug,
                "display_name": display_name,
                "reason": str(e),
            })
            error(f"Monster builder exception for {display_name}: {e}", category="module_generation")

    return results


def ensure_monster_reference_closure(
    module_name: str,
    module_dir: str,
) -> Dict[str, Any]:
    """Ensure all monster references have corresponding stat files.

    Orchestrates the full closure workflow: collect referenced monsters,
    identify existing files, detect NPC-like ambiguous names, materialize
    missing stat blocks, and save a closure report.

    Args:
        module_name: Name of the module.
        module_dir: Path to the module directory.

    Returns:
        Closure report dict with:
            - timestamp: ISO timestamp
            - required: count of referenced monsters
            - existing_before: count of existing monster files
            - generated: count of newly generated monsters
            - unresolved: count of unresolved references
            - details: dict with generation results and unresolved list
            - ambiguous_npc_like: list of slugs identified as NPC-like
    """
    closure_report: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "required": 0,
        "existing_before": 0,
        "generated": 0,
        "unresolved": 0,
        "details": {},
        "ambiguous_npc_like": [],
    }

    referenced = collect_referenced_monsters(module_dir)
    closure_report["required"] = len(referenced)

    if not referenced:
        info("No monster references found in module areas", category="module_generation")
        return closure_report

    existing = collect_existing_monster_slugs(module_dir)
    closure_report["existing_before"] = len(existing)

    missing = {slug: m_info for slug, m_info in referenced.items() if slug not in existing}

    info(
        f"Monster reference closure: {len(referenced)} required, "
        f"{len(existing)} existing, {len(missing)} missing",
        category="module_generation",
    )

    # Detect NPC-like ambiguous names among missing monsters
    ambiguous_npc_like: List[str] = []
    for slug, m_info in missing.items():
        display_name = m_info["original_names"][0] if m_info.get("original_names") else slug
        if _is_ambiguous_npc_like(display_name, slug):
            ambiguous_npc_like.append(slug)
            warning(
                f"Ambiguous NPC-like monster reference: {display_name} ({slug})",
                category="module_generation",
            )
    closure_report["ambiguous_npc_like"] = ambiguous_npc_like

    if missing:
        generation_results = materialize_missing_monsters(module_name, module_dir, missing)
        closure_report["details"]["generation"] = generation_results
        closure_report["generated"] = len(generation_results["generated"])

        existing_after = collect_existing_monster_slugs(module_dir)
        still_missing = {slug: m_info for slug, m_info in referenced.items() if slug not in existing_after}
        closure_report["unresolved"] = len(still_missing)

        if still_missing:
            closure_report["details"]["unresolved"] = [
                {
                    "slug": slug,
                    "original_names": m_info["original_names"],
                    "sources": m_info["sources"][:3],
                }
                for slug, m_info in still_missing.items()
            ]
            error(
                f"Monster reference closure failed: {len(still_missing)} unresolved references",
                category="module_generation",
            )
        else:
            info("Monster reference closure complete: all references resolved", category="module_generation")
    else:
        info("Monster reference closure complete: no missing references", category="module_generation")

    report_path = os.path.join(module_dir, "monster_closure_report.json")
    try:
        if safe_write_json(report_path, closure_report):
            info(f"Monster closure report saved to {report_path}", category="module_generation")
        else:
            warning(
                f"Could not save monster closure report: write returned False for {report_path}",
                category="module_generation",
            )
    except Exception as e:
        warning(f"Could not save monster closure report: {e}", category="module_generation")

    return closure_report
