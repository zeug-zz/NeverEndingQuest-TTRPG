# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest NPC Identity - Canonical NPC identity helpers
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class NPCIdentity:
    """Canonical NPC identity plus preserved source metadata."""

    canonical_name: str
    slug: str
    source_label: str
    source_id: Optional[str] = None
    role_hint: Optional[str] = None


def canonicalize_npc_slug(raw: str) -> str:
    """Build a stable NPC slug from a canonical identity name."""
    normalized = (raw or "").strip().lower()
    normalized = normalized.replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unnamed_npc"


def canonicalize_npc_identity(label: str, fallback_id: Optional[str] = None) -> NPCIdentity:
    """Split a source NPC label into canonical name, slug, and metadata.

    Labels like "Arannis, vault scholar and alarmed archivist" carry an
    appositive role phrase after the comma. The canonical identity is the
    proper-name prefix; the suffix is preserved as a role hint.
    """
    source_label = str(label or fallback_id or "").strip()
    source_id = str(fallback_id).strip() if fallback_id else None

    canonical_name = source_label
    role_hint = None
    if "," in source_label:
        prefix, suffix = source_label.split(",", 1)
        prefix = prefix.strip()
        suffix = suffix.strip()
        if _is_usable_identity_prefix(prefix):
            canonical_name = prefix
            role_hint = suffix or None

    if not canonical_name and source_id:
        canonical_name = source_id.replace("_", " ").strip()

    canonical_name = canonical_name or "Unnamed NPC"
    return NPCIdentity(
        canonical_name=canonical_name,
        slug=canonicalize_npc_slug(canonical_name),
        source_label=source_label or canonical_name,
        source_id=source_id,
        role_hint=role_hint,
    )


def get_npc_compendium_lookup_keys(raw_id: str, raw_name: Optional[str] = None) -> List[str]:
    """Return canonical and legacy lookup keys for NPC compendium reads."""
    keys: List[str] = []
    for value in (raw_name, raw_id):
        if not value:
            continue
        identity = canonicalize_npc_identity(value, fallback_id=raw_id)
        for candidate in (identity.slug, canonicalize_npc_slug(value), str(value).strip()):
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


def merge_npc_identity_metadata(entry: Dict[str, Any], identity: NPCIdentity) -> Dict[str, Any]:
    """Merge source identity metadata into an NPC compendium or temp entry."""
    entry["name"] = identity.canonical_name
    if identity.source_label and identity.source_label != identity.canonical_name:
        entry["source_label"] = identity.source_label
        _append_unique(entry, "source_labels", identity.source_label)
    if identity.source_id and identity.source_id != identity.slug:
        entry["source_id"] = identity.source_id
        _append_unique(entry, "source_ids", identity.source_id)
    if identity.role_hint:
        entry["role_hint"] = identity.role_hint
        _append_unique(entry, "role_hints", identity.role_hint)
    return entry


def build_npc_asset_payload(identity: NPCIdentity, asset_type: str = "npc") -> Dict[str, Any]:
    """Build a toolkit asset payload for a canonicalized NPC identity."""
    payload = {
        "id": identity.slug,
        "name": identity.canonical_name,
        "type": asset_type,
    }
    if identity.source_label and identity.source_label != identity.canonical_name:
        payload["source_label"] = identity.source_label
    if identity.source_id and identity.source_id != identity.slug:
        payload["source_id"] = identity.source_id
    if identity.role_hint:
        payload["role_hint"] = identity.role_hint
    return payload


def _is_usable_identity_prefix(prefix: str) -> bool:
    if not prefix:
        return False
    words = prefix.split()
    if len(words) > 4:
        return False
    return any(char.isalpha() for char in prefix)


def _append_unique(entry: Dict[str, Any], key: str, value: str) -> None:
    values = entry.get(key)
    if not isinstance(values, list):
        values = []
    if value not in values:
        values.append(value)
    entry[key] = values
