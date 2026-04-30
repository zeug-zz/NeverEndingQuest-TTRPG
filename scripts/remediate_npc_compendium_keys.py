#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""NeverEndingQuest - NPC Compendium Canonical Key Remediation

Remediate legacy descriptive NPC keys in data/bestiary/npc_compendium.json.

Default mode is dry-run. Use --apply to write the canonicalized compendium
and create an audit report alongside the source file.
"""

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.file_operations import safe_read_json, safe_write_json
from utils.npc_identity import (
    NPCIdentity,
    canonicalize_npc_identity,
    merge_npc_identity_metadata,
)


DEFAULT_COMPILED_PATH = Path("data/bestiary/npc_compendium.json")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_description(value: Any) -> str:
    return _normalize_text(value)


def _entry_priority(source_key: str, entry: Dict[str, Any], canonical_key: str) -> Tuple[int, str]:
    has_description = bool(_normalize_description(entry.get("description")))
    if source_key == canonical_key and has_description:
        return (0, source_key)
    if has_description:
        return (1, source_key)
    if source_key == canonical_key:
        return (2, source_key)
    return (3, source_key)


def _build_alternate_description(
    source_key: str,
    entry: Dict[str, Any],
    identity: NPCIdentity,
) -> Dict[str, Any]:
    alt = {
        "legacy_id": source_key,
        "source_label": identity.source_label,
        "description": _normalize_description(entry.get("description")),
    }
    if identity.role_hint:
        alt["role_hint"] = identity.role_hint
    if entry.get("module"):
        alt["module"] = entry.get("module")
    if entry.get("generated_at"):
        alt["generated_at"] = entry.get("generated_at")
    if entry.get("original_generated_at"):
        alt["original_generated_at"] = entry.get("original_generated_at")
    return alt


def _append_unique_dict(entry: Dict[str, Any], key: str, value: Dict[str, Any]) -> None:
    values = entry.get(key)
    if not isinstance(values, list):
        values = []
    if value not in values:
        values.append(value)
    entry[key] = values


def _build_canonical_npc_entry(
    canonical_key: str,
    entries: List[Tuple[str, Dict[str, Any], NPCIdentity]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ordered_entries = sorted(entries, key=lambda item: _entry_priority(item[0], item[1], canonical_key))
    base_source_key, base_entry, base_identity = ordered_entries[0]
    canonical_entry = copy.deepcopy(base_entry)
    canonical_entry = merge_npc_identity_metadata(canonical_entry, base_identity)

    canonical_description = _normalize_description(canonical_entry.get("description"))
    if not canonical_description:
        for source_key, entry, _identity in ordered_entries[1:]:
            description = _normalize_description(entry.get("description"))
            if description:
                canonical_description = description
                canonical_entry["description"] = description
                break

    if not canonical_entry.get("description"):
        canonical_entry["description"] = ""

    _append_unique_dict(canonical_entry, "merged_from", {"legacy_id": base_source_key, "source_label": base_identity.source_label})
    _append_unique_dict(canonical_entry, "alternate_descriptions", {})  # placeholder reset removed below
    canonical_entry["alternate_descriptions"] = []
    canonical_entry["legacy_ids"] = []

    for source_key, entry, identity in ordered_entries:
        if source_key != canonical_key:
            canonical_entry["legacy_ids"].append(source_key)

        if identity.source_label and identity.source_label != identity.canonical_name:
            current_labels = canonical_entry.get("source_labels")
            if not isinstance(current_labels, list):
                current_labels = []
            if identity.source_label not in current_labels:
                current_labels.append(identity.source_label)
            canonical_entry["source_labels"] = current_labels

        if identity.source_id and identity.source_id != identity.slug:
            current_ids = canonical_entry.get("source_ids")
            if not isinstance(current_ids, list):
                current_ids = []
            if identity.source_id not in current_ids:
                current_ids.append(identity.source_id)
            canonical_entry["source_ids"] = current_ids

        if identity.role_hint:
            current_roles = canonical_entry.get("role_hints")
            if not isinstance(current_roles, list):
                current_roles = []
            if identity.role_hint not in current_roles:
                current_roles.append(identity.role_hint)
            canonical_entry["role_hints"] = current_roles

        description = _normalize_description(entry.get("description"))
        if description and description != canonical_description:
            _append_unique_dict(canonical_entry, "alternate_descriptions", _build_alternate_description(source_key, entry, identity))

    # Clean up any accidental placeholder insertion and keep the structure stable.
    canonical_entry.pop("merged_from", None)

    return canonical_entry, {
        "canonical_key": canonical_key,
        "canonical_name": canonical_entry.get("name", canonical_key),
        "base_source_key": base_source_key,
        "source_count": len(entries),
        "legacy_ids": list(canonical_entry.get("legacy_ids", [])),
        "alternate_count": len(canonical_entry.get("alternate_descriptions", [])),
    }


def remediate_npc_compendium_data(compendium: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a remediated copy of the NPC compendium and a structured report."""
    raw_npcs = compendium.get("npcs", {})
    if not isinstance(raw_npcs, dict):
        raise ValueError("Compendium missing npcs mapping")

    grouped: Dict[str, List[Tuple[str, Dict[str, Any], NPCIdentity]]] = {}
    skipped: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []

    for source_key, raw_entry in raw_npcs.items():
        if not isinstance(raw_entry, dict):
            skipped.append({"source_key": source_key, "reason": "non_dict_entry"})
            continue

        source_name = _normalize_text(raw_entry.get("name") or source_key)
        identity = canonicalize_npc_identity(source_name, fallback_id=source_key)
        if not identity.slug:
            skipped.append({"source_key": source_key, "reason": "unusable_identity"})
            continue

        grouped.setdefault(identity.slug, []).append((source_key, raw_entry, identity))

    remediated_npcs: Dict[str, Dict[str, Any]] = {}
    mappings: List[Dict[str, Any]] = []
    merged_groups = 0

    for canonical_key in sorted(grouped.keys()):
        entries = grouped[canonical_key]
        canonical_entry, group_report = _build_canonical_npc_entry(canonical_key, entries)
        remediated_npcs[canonical_key] = canonical_entry
        if group_report["source_count"] > 1:
            merged_groups += 1
        mappings.append(group_report)

        for source_key, raw_entry, identity in entries:
            if source_key == canonical_key and identity.slug == canonical_key and identity.source_label == identity.canonical_name:
                kept.append({"source_key": source_key, "canonical_key": canonical_key})
            elif source_key == canonical_key:
                kept.append({"source_key": source_key, "canonical_key": canonical_key})

    remediated_compendium = copy.deepcopy(compendium)
    remediated_compendium["npcs"] = remediated_npcs
    remediated_compendium["total_npcs"] = len(remediated_npcs)

    report = {
        "mode": "analyze",
        "path": "",
        "scanned": len(raw_npcs),
        "canonical_npcs": len(remediated_npcs),
        "merged_groups": merged_groups,
        "kept_entries": len(kept),
        "skipped_entries": skipped,
        "mappings": mappings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backup_path": None,
        "report_path": None,
    }
    return remediated_compendium, report


def build_report_path(compendium_path: Path) -> Path:
    return compendium_path.with_name(f"{compendium_path.stem}.remediation_report.json")


def remediate_npc_compendium_file(compendium_path: Path, apply_changes: bool = False) -> Dict[str, Any]:
    """Remediate a compendium file and return a structured report."""
    data = safe_read_json(str(compendium_path))
    if not data:
        raise FileNotFoundError(f"Unable to read compendium: {compendium_path}")
    if not isinstance(data, dict):
        raise ValueError("Compendium root must be a JSON object")

    remediated, report = remediate_npc_compendium_data(data)
    report["path"] = str(compendium_path)
    report["report_path"] = str(build_report_path(compendium_path))

    if apply_changes:
        backup_path = f"{compendium_path}.bak"
        report["mode"] = "apply"
        report["backup_path"] = backup_path
        report_path = build_report_path(compendium_path)
        if not safe_write_json(str(report_path), report):
            raise IOError(f"Failed to write audit report: {report_path}")
        if not safe_write_json(str(compendium_path), remediated):
            raise IOError(f"Failed to write remediated compendium: {compendium_path}")
        report["report_path"] = str(report_path)
    else:
        report["mode"] = "dry-run"

    return report


def _format_human_report(report: Dict[str, Any]) -> str:
    lines = [
        "NPC COMPREHENSIVE KEY REMEDIATION",
        f"Mode: {report['mode']}",
        f"Path: {report['path']}",
        f"Scanned: {report['scanned']}",
        f"Canonical NPCs: {report['canonical_npcs']}",
        f"Merged groups: {report['merged_groups']}",
        f"Kept entries: {report['kept_entries']}",
        f"Skipped entries: {len(report['skipped_entries'])}",
    ]
    if report.get("backup_path"):
        lines.append(f"Backup: {report['backup_path']}")
    if report.get("report_path"):
        lines.append(f"Audit report: {report['report_path']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remediate canonical keys in data/bestiary/npc_compendium.json",
    )
    parser.add_argument(
        "--path",
        default=str(DEFAULT_COMPILED_PATH),
        help="Path to npc_compendium.json (default: data/bestiary/npc_compendium.json)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--apply", action="store_true", help="Write the remediated compendium")
    mode_group.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--json", action="store_true", default=False, help="Emit JSON output")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    compendium_path = Path(args.path)
    apply_changes = bool(args.apply)

    try:
        report = remediate_npc_compendium_file(compendium_path, apply_changes=apply_changes)
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "error", "path": str(compendium_path), "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"[ERROR] {exc}")
        return 1

    output = {
        "status": "ok",
        **report,
    }

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(_format_human_report(output))
        if apply_changes:
            print("Applied canonical NPC key remediation.")
        else:
            print("Dry run complete. Use --apply to write changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
