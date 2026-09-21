# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Community Tools - Monster Builder
Copyright (c) 2024 MoonlightByte
Licensed under Apache License 2.0

See LICENSE-APACHE file for full terms.
"""

# ============================================================================
# MONSTER_BUILDER.PY - CONTENT GENERATION LAYER - MONSTERS
# ============================================================================
#
# ARCHITECTURE ROLE: Content Generation Layer - AI-Powered Monster Creation
#
# This module implements our Factory Pattern for monster creation, using
# AI-powered generation with strict schema validation. It demonstrates our
# "Schema-Driven Development" approach to content creation.
#
# KEY RESPONSIBILITIES:
# - Generate 5e compliant monsters using AI
# - Validate all generated content against monster schema
# - Handle AI response parsing and cleanup
# - Provide robust error handling and validation feedback
# - Save generated monsters to module-specific directories
#
# AI GENERATION PIPELINE:
# Schema Template -> AI Prompt -> Response Generation -> JSON Parsing ->
# Schema Validation -> File Persistence -> Path Resolution
#
# VALIDATION STRATEGY:
# - JSON schema compliance checking
# - Automatic cleanup of AI response artifacts
# - Nested value field flattening
# - 5e rule validation through schema constraints
#
# ARCHITECTURAL INTEGRATION:
# - Uses ModulePathManager for file operations
# - Integrates with mon_schema.json for validation
# - Called by DMs and automated module generation
# - Implements our "Defense in Depth" validation approach
#
# DESIGN PATTERNS:
# - Factory Pattern: Creates monsters based on specifications
# - Template Method: Consistent generation and validation pipeline
# - Strategy Pattern: Configurable AI models for generation
#
# This module exemplifies our approach to AI-powered content generation
# while maintaining strict data integrity and 5e rule compliance.
# ============================================================================

import json
import sys
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

# Add the project root to the Python path so we can import from utils, core, etc.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from jsonschema import validate, ValidationError
import config
from utils.module_path_manager import ModulePathManager
from utils.monster_reference_closure import normalize_monster_name
from utils.enhanced_logger import debug, info, warning, error, set_script_name
from utils.ai_client_factory import (
    create_chat_client,
    get_chat_completion_params,
    get_model_config,
    handle_provider_error,
)

# Set script name for logging
set_script_name("monster_builder")

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def load_schema(file_name, adaptation_safe_output=False):
    try:
        with open(file_name, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        if not adaptation_safe_output:
            print(f"{RED}Error: File {file_name} not found.{RESET}")
        return None
    except json.JSONDecodeError:
        if not adaptation_safe_output:
            print(f"{RED}Error: Invalid JSON in {file_name}.{RESET}")
        return None


def save_json(file_name, data, adaptation_safe_output=False):
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_name)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            if not adaptation_safe_output:
                print(f"{YELLOW}Created directory: {directory}{RESET}")

        with open(file_name, "w") as file:
            json.dump(data, file, indent=2)
        if not adaptation_safe_output:
            info(f"SUCCESS: Monster save ({file_name}) - PASS", category="monster_creation")
        return True
    except Exception as e:
        if not adaptation_safe_output:
            print(f"{RED}Error saving to {file_name}: {str(e)}{RESET}")
        return False


def _format_authored_context(authored_context: Optional[Dict[str, Any]]) -> str:
    """Build bounded authored context block for monster generation."""
    if not isinstance(authored_context, dict):
        return ""

    lines = []

    module_name = str(authored_context.get("module") or "").strip()
    if module_name:
        lines.append(f"Module: {module_name}")

    level_range = authored_context.get("level_range")
    if isinstance(level_range, str) and level_range.strip():
        lines.append(f"Recommended level range: {level_range.strip()}")

    difficulty = str(authored_context.get("difficulty") or "").strip()
    if difficulty:
        lines.append(f"Encounter difficulty guidance: {difficulty}")

    area_context = authored_context.get("area_context")
    if isinstance(area_context, list):
        area_lines = []
        for entry in area_context[:3]:
            if not isinstance(entry, dict):
                continue
            area_name = str(entry.get("area_name") or "").strip()
            location_name = str(entry.get("location_name") or "").strip()
            location_id = str(entry.get("location_id") or "").strip()
            prose = str(entry.get("location_prose") or "").strip()
            label_parts = [
                part for part in [area_name, location_name or location_id] if part
            ]
            label = " / ".join(label_parts)
            if label and prose:
                area_lines.append(f"- {label}: {prose[:220]}")
            elif label:
                area_lines.append(f"- {label}")

        if area_lines:
            lines.append("Authored location context:")
            lines.extend(area_lines)

    if not lines:
        return ""

    return "\n\nAUTHORED CONTEXT (USE ONLY IF PROVIDED):\n" + "\n".join(lines)


def generate_monster(
    monster_name,
    schema,
    party_level=1,
    authored_context: Optional[Dict[str, Any]] = None,
    adaptation_safe_output=False,
):
    # Build context-aware system prompt
    system_content = """You are an assistant that creates monster schema JSON files from a master monster schema template for a 5e game. Given a monster name, create a JSON representation of the monster's stats and abilities according to 5e rules following the monster schema template exactly.

CRITICAL RULE - MONSTER SCALING:
- NEVER scale UP monster stats from their standard values
- Standard monsters (Giant Rat, Goblin, Orc, etc.) MUST use their official stats
- Giant Rat = CR 1/4, 7 HP - regardless of party level
- Goblin = CR 1/4, 7 HP - regardless of party level  
- Orc = CR 1/2, 15 HP - regardless of party level
- For low-level parties (level 1-2), you may scale DOWN hit points, but NEVER scale UP
- To challenge higher level parties, use MORE monsters or DIFFERENT monsters, not buffed versions

CHALLENGE RATING GUIDANCE:
- Party Level 1: CR 1/8 to CR 1/2 for normal encounters, CR 1 for boss encounters
- Party Level 2: CR 1/4 to CR 1 for normal encounters, CR 2 for boss encounters  
- Party Level 3: CR 1/2 to CR 1 for normal encounters, CR 2-3 for boss encounters
- Party Level 4: CR 1/2 to CR 2 for normal encounters, CR 3-4 for boss encounters
- Party Level 5+: Scale accordingly, normal encounters should be CR (level-2) to CR (level), bosses CR (level+1) to CR (level+2)

ENCOUNTER BALANCE:
- "low" danger: Use lower end of CR range
- "medium" danger: Use middle of CR range  
- "high" danger: Use higher end of CR range, consider adding special abilities
- Multiple monsters: Reduce individual CR but increase tactical complexity

NAMING CONVENTIONS:
- ALWAYS use SINGULAR names (e.g., "Orc", "Skeleton", "Goblin")
- NEVER use plural names (e.g., "Orcs", "Skeletons", "Goblins")
- If a plural name is provided, convert to singular form automatically
- For generic names like "Orc_1" or "Bandit_2", use standard Monster Manual names and stats
- For unique names, create custom monsters with that exact name
- For corrupted/themed variants, add appropriate descriptors and abilities

SPELLCASTING MONSTERS:
- If the monster is described as a spellcaster (wizard, sorcerer, cleric, druid, etc.), include the "spellcasting" property
- Human spellcasters should have type "Humanoid", not "Fiend" or other types
- Sorcerers use Charisma, Wizards use Intelligence, Clerics/Druids use Wisdom
- CR 1: Usually has cantrips and 1st level spells (2-3 spell slots)
- CR 2-3: Has cantrips, 1st and 2nd level spells (4-6 total spell slots)
- CR 4-5: Has up to 3rd level spells
- Calculate spell save DC as: 8 + proficiency bonus + ability modifier
- Calculate spell attack bonus as: proficiency bonus + ability modifier
- Choose appropriate spells for the monster's theme and CR

Ensure your new monster JSON adheres to the provided schema template. Do not include any additional properties or nested 'type' and 'value' fields. For non-spellcasters, omit the spellcasting property entirely. Return only the JSON content without any markdown formatting."""

    # Build context-aware user prompt
    context_block = _format_authored_context(authored_context)

    user_content = f"""Create a monster named '{monster_name}' using 5e rules.

PARTY LEVEL: {party_level}

CRITICAL NAMING REQUIREMENT:
- The monster name MUST be in SINGULAR form (e.g., "Orc", "Skeleton", "Goblin")
- If the provided name is plural (e.g., "Orcs", "Skeletons", "Goblins"), convert to singular
- Use singular names regardless of how many creatures will be in the encounter

IMPORTANT: If this is a standard monster (Giant Rat, Goblin, Orc, etc.), use the EXACT official stats. Do NOT scale up HP or other stats based on party level. A Giant Rat always has 7 HP, regardless of party level.

Only create custom stats for unique named monsters or special variants (e.g., "Corrupted Giant Rat" or "Elder Goblin").

If this monster name includes terms like 'sorcerer', 'wizard', 'cleric', 'druid', 'warlock', 'mage', or other spellcasting classes, make sure to include the spellcasting property with appropriate spells for their CR.

If AUTHORED CONTEXT is provided below, align creature type, movement style, and narrative flavor to that context while keeping strict 5e SRD-compatible mechanics and schema compliance.

{context_block}

Schema: {json.dumps(schema)}"""

    prompt = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    try:
        client = create_chat_client()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    **get_chat_completion_params(
                        "monster_builder",
                        config.MONSTER_BUILDER_MODEL,
                        temperature_override=0.7,
                    ),
                    messages=prompt,
                )
                break
            except Exception as e:
                error_result = handle_provider_error(e, "generate_monster")
                if error_result["should_fallback"] and attempt < max_retries - 1:
                    client = create_chat_client(use_fallback=True)
                    continue
                raise

        ai_response = response.choices[0].message.content.strip()
        if not adaptation_safe_output:
            print(f"{YELLOW}AI Response:{RESET}\n{ai_response}")

        # Remove markdown code block if present
        ai_response = re.sub(
            r"^```json\s*|\s*```$", "", ai_response, flags=re.MULTILINE
        )

        try:
            monster_data = json.loads(ai_response)
            # Remove the outer "properties" object if it exists
            if "properties" in monster_data:
                monster_data = monster_data["properties"]
            # Remove nested 'value' fields if they exist
            monster_data = remove_nested_values(monster_data)
            validate(instance=monster_data, schema=schema)
            return monster_data
        except json.JSONDecodeError as e:
            if not adaptation_safe_output:
                print(f"{RED}Error: Invalid JSON in AI response. {str(e)}{RESET}")
                print(f"{YELLOW}Processed AI response:{RESET}\n{ai_response}")
        except ValidationError as e:
            if not adaptation_safe_output:
                print(
                    f"{RED}Error: Generated monster data does not match schema. {str(e)}{RESET}"
                )
                print(
                    f"{YELLOW}Processed monster data:{RESET}\n{json.dumps(monster_data, indent=2)}"
                )  # Added indent for readability
    except Exception as e:
        if not adaptation_safe_output:
            print(f"{RED}Error: Failed to generate monster data. {str(e)}{RESET}")

    return None


def remove_nested_values(data):
    if isinstance(data, dict):
        return {
            k: remove_nested_values(
                v["value"] if isinstance(v, dict) and "value" in v else v
            )
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [remove_nested_values(item) for item in data]
    else:
        return data


def _is_path_within(path, root):
    """Return whether *path* resolves inside *root*, including root itself."""
    try:
        Path(path).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _prepare_explicit_output_directory(output_directory):
    """Prepare and validate an explicit monster output root.

    The caller supplies the root directory; generated files are always placed
    in its direct ``monsters`` child. Symlinked roots and monster directories
    are rejected so a requested staging root cannot redirect writes elsewhere.
    """
    if not isinstance(output_directory, (str, os.PathLike)):
        raise ValueError("Explicit output directory must be a directory path")

    output_root_value = os.fspath(output_directory)
    if isinstance(output_root_value, bytes):
        raise ValueError("Explicit output directory must be a text path")
    if not output_root_value.strip():
        raise ValueError("Explicit output directory must not be empty")

    output_root_path = os.path.abspath(os.path.expanduser(output_root_value))
    if os.path.lexists(output_root_path) and os.path.islink(output_root_path):
        raise ValueError("Explicit output directory must not be a symlink")
    if os.path.exists(output_root_path) and not os.path.isdir(output_root_path):
        raise ValueError("Explicit output directory must be a directory")

    try:
        os.makedirs(output_root_path, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create explicit output directory: {exc}") from exc

    monsters_path = os.path.join(output_root_path, "monsters")
    if os.path.lexists(monsters_path) and os.path.islink(monsters_path):
        raise ValueError("Explicit monsters directory must not be a symlink")
    if os.path.exists(monsters_path) and not os.path.isdir(monsters_path):
        raise ValueError("Explicit monsters path must be a directory")

    try:
        os.makedirs(monsters_path, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create explicit monsters directory: {exc}") from exc

    root_real = os.path.realpath(output_root_path)
    monsters_real = os.path.realpath(monsters_path)
    if not _is_path_within(monsters_real, root_real):
        raise ValueError("Explicit monsters directory escapes the output root")

    return output_root_path, monsters_path


def _resolve_monster_output_path(monster_name, path_manager, output_directory=None):
    """Resolve a monster path while preserving legacy module path behavior."""
    if output_directory is None:
        return path_manager.get_monster_path(monster_name)

    output_root, monsters_path = _prepare_explicit_output_directory(output_directory)
    # Explicit output is the adaptation staging path.  Use the closure slug
    # contract here so possessive names do not diverge from final consistency
    # checks.  The omitted-output legacy path remains ModulePathManager-based.
    slug = normalize_monster_name(str(monster_name or ""))
    if not slug or os.path.basename(slug) != slug:
        raise ValueError("Monster name did not produce a safe canonical filename")

    target_path = os.path.join(monsters_path, f"{slug}.json")
    if os.path.lexists(target_path) and os.path.islink(target_path):
        raise ValueError("Explicit monster target must not be a symlink")
    if not _is_path_within(os.path.realpath(target_path), os.path.realpath(output_root)):
        raise ValueError("Monster target escapes the explicit output root")
    return target_path


def _create_argument_parser():
    """Create the monster builder command-line parser."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate monster stat blocks")
    parser.add_argument("monster_name", help="Name of the monster to generate")
    parser.add_argument(
        "--module", "-m", help="Module name for path resolution (optional)"
    )
    parser.add_argument(
        "--level", "-l", type=int, default=None, help="Average party level (optional)"
    )
    parser.add_argument(
        "--context-file",
        help="Optional JSON file with authored monster context metadata",
    )
    parser.add_argument(
        "--output-directory",
        "--output-dir",
        dest="output_directory",
        default=None,
        help="Explicit output root; saves the monster under its monsters directory",
    )
    parser.add_argument(
        "--adaptation-safe-output",
        action="store_true",
        help="Suppress raw generation diagnostics for adaptation subprocesses",
    )
    return parser


def main():
    args = _create_argument_parser().parse_args()
    monster_name_arg = args.monster_name

    # Get average party level
    party_level = args.level if args.level else 1
    if not args.level:
        try:
            from utils.encoding_utils import safe_json_load

            party_tracker = safe_json_load("party_tracker.json")
            if party_tracker and party_tracker.get("partyMembers"):
                levels = []
                for character_name in party_tracker["partyMembers"]:
                    character_data = safe_json_load(f"characters/{character_name}.json")
                    if character_data:
                        levels.append(character_data.get("level", 1))
                if levels:
                    party_level = round(sum(levels) / len(levels))
        except:
            party_level = 1

    schema_data = load_schema(
        "schemas/mon_schema.json",
        adaptation_safe_output=args.adaptation_safe_output,
    )
    if not schema_data:
        return

    authored_context = None
    if args.context_file:
        authored_context = load_schema(
            args.context_file,
            adaptation_safe_output=args.adaptation_safe_output,
        )
        if authored_context is None:
            if not args.adaptation_safe_output:
                warning(
                    f"AUTHORED_CONTEXT: Failed to load context file {args.context_file}; continuing without context",
                    category="monster_creation",
                )

    generated_monster_data = generate_monster(
        monster_name_arg,
        schema_data,
        party_level,
        authored_context=authored_context,
        adaptation_safe_output=args.adaptation_safe_output,
    )
    if generated_monster_data:
        # Use provided module name or fall back to party tracker
        current_module = None
        if args.module:
            current_module = args.module.replace(" ", "_")
        else:
            try:
                from utils.encoding_utils import safe_json_load

                party_tracker = safe_json_load("party_tracker.json")
                current_module = (
                    party_tracker.get("module", "").replace(" ", "_")
                    if party_tracker
                    else None
                )
            except:
                pass

        path_manager = ModulePathManager(current_module)
        try:
            full_path = _resolve_monster_output_path(
                monster_name_arg,
                path_manager,
                output_directory=args.output_directory,
            )
        except (OSError, ValueError) as exc:
            if not args.adaptation_safe_output:
                error(
                    f"FAILURE: Monster save ({monster_name_arg}) - {str(exc)}",
                    category="monster_creation",
                )
            sys.exit(1)
        if save_json(
            full_path,
            generated_monster_data,
            adaptation_safe_output=args.adaptation_safe_output,
        ):
            if not args.adaptation_safe_output:
                info(
                    f"SUCCESS: Monster creation ({monster_name_arg}) - PASS",
                    category="monster_creation",
                )
        else:
            if not args.adaptation_safe_output:
                error(
                    f"FAILURE: Monster save ({monster_name_arg}) - FAIL",
                    category="monster_creation",
                )
            sys.exit(1)  # Ensure exit with error code
    else:
        if not args.adaptation_safe_output:
            error(
                f"FAILURE: Monster creation ({monster_name_arg}) - FAIL",
                category="monster_creation",
            )
        sys.exit(1)  # Exit with an error code


if __name__ == "__main__":
    main()
