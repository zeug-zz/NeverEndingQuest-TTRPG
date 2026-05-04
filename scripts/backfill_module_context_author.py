# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Module Tools - Backfill author/license fields
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Backfill author and license fields into all module_context.json files.
Adds "author": "" and "license": "" if missing. Idempotent.

Usage:
  python3 scripts/backfill_module_context_author.py --dry-run   (default, safe)
  python3 scripts/backfill_module_context_author.py --apply     (write changes)
"""

import sys
from pathlib import Path

# Ensure repo root is on path for project imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from utils.file_operations import safe_read_json, safe_write_json
from utils.enhanced_logger import info, warning, error


def find_context_files(repo_root: Path):
    """Yield (module_name, path) for all module_context.json and module_context_BU.json."""
    for path in sorted(repo_root.glob("modules/*/module_context.json")):
        yield path.parent.name, path
    for path in sorted(repo_root.glob("modules/*/module_context_BU.json")):
        yield path.parent.name, path


def backfill_file(filepath: Path, apply: bool):
    """Add author/license if missing. Returns (added, error)."""
    try:
        data = safe_read_json(str(filepath))
    except Exception as e:
        return False, str(e)

    if data is None:
        return False, "could not read"

    if "author" in data and "license" in data:
        return False, None  # already present, skip

    added = 0
    if "author" not in data:
        data["author"] = ""
        added += 1
    if "license" not in data:
        data["license"] = ""
        added += 1

    if apply:
        try:
            safe_write_json(str(filepath), data)
        except Exception as e:
            return False, str(e)

    return True, None


def main():
    parser = argparse.ArgumentParser(
        description="Backfill author/license into module_context files"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default: dry-run)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    files = list(find_context_files(repo_root))

    if not files:
        print("No module_context files found.")
        return

    added = 0
    skipped = 0
    errors = 0

    for module_name, filepath in files:
        is_bu = "_BU" in filepath.name
        label = f"{module_name}/{'BU' if is_bu else 'live'}"

        was_added, err = backfill_file(filepath, args.apply)
        if err:
            error(f"{label}: ERROR - {err}")
            errors += 1
        elif was_added:
            print(f"[{'ADD' if args.apply else 'DRY'}] {label} {filepath.name}")
            added += 1
        else:
            skipped += 1

    mode = "applied" if args.apply else "would apply (dry-run)"
    total = len(files)
    print(
        f"\nSummary ({mode}): {total} files, {added} updated, "
        f"{skipped} ok, {errors} errors"
    )
    if not args.apply:
        print("Use --apply to write changes.")


if __name__ == "__main__":
    main()
