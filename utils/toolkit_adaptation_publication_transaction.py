# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - LLM Adaptation Publication Transaction
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Python-owned snapshot and rollback helpers for the explicit LLM adaptation
publication lane. The helpers capture the pre-registration registry and
campaign state, restore valid prior JSON atomically, remove files that were
created by a failed transaction, and verify the restored state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from utils.enhanced_logger import error
from utils.file_operations import safe_read_json, safe_write_json


ADAPTATION_PUBLICATION_TRANSACTION_CONTRACT_VERSION = (
    "toolkit_adaptation_publication_transaction.v1"
)
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")


def _resolve_path(path: Path) -> Path:
    """Resolve a transaction path without changing its caller-selected root."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _validate_module_slug(module_slug: Any) -> str:
    """Validate the Python-owned module identity used by a transaction."""
    if not isinstance(module_slug, str) or not _MODULE_SLUG_RE.fullmatch(module_slug):
        raise ValueError("module_slug is not path-safe")
    return module_slug


def _strict_equal(expected: Any, actual: Any) -> bool:
    """Compare JSON values while preserving scalar types."""
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, Mapping):
        if set(expected) != set(actual):
            return False
        return all(_strict_equal(expected[key], actual[key]) for key in expected)
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(
            _strict_equal(expected_value, actual_value)
            for expected_value, actual_value in zip(expected, actual)
        )
    return expected == actual


def _canonical_hash(payload: Any) -> str:
    """Build a deterministic transaction identity from bounded JSON state."""
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_text(path: Path) -> str:
    """Read bounded rollback text without exposing it in public results."""
    return path.read_text(encoding="utf-8")


def _capture_campaign_state(path: Path) -> Dict[str, Any]:
    """Capture campaign state, including an invalid file for safe restoration."""
    state: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "valid_json_object": False,
        "payload": None,
        "raw_text": None,
    }
    if not path.exists():
        return state
    if not path.is_file() or path.is_symlink():
        state["raw_text"] = None
        return state
    try:
        payload = safe_read_json(str(path))
    except Exception:
        payload = None
    if isinstance(payload, Mapping):
        state["valid_json_object"] = True
        state["payload"] = copy.deepcopy(dict(payload))
        return state
    try:
        state["raw_text"] = _read_text(path)
    except Exception:
        state["raw_text"] = None
    return state


def capture_adaptation_publication_snapshot(
    module_slug: str,
    *,
    registry_path: Path,
    campaign_path: Optional[Path] = None,
    area_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Capture pre-write state for one adaptation publication transaction.

    The full valid JSON envelopes are kept in the private snapshot returned to
    the same Python transaction. Public metadata contains only identity and
    pre-existing-entry facts, so reports do not copy the runtime registry or
    campaign payloads.
    """
    try:
        slug = _validate_module_slug(module_slug)
        resolved_registry = _resolve_path(registry_path)
        resolved_campaign = _resolve_path(
            campaign_path
            if campaign_path is not None
            else resolved_registry.parent / "campaign.json"
        )
        if not resolved_registry.is_file() or resolved_registry.is_symlink():
            raise ValueError("registry_missing")
        registry_payload = safe_read_json(str(resolved_registry))
        if not isinstance(registry_payload, Mapping):
            raise ValueError("registry_malformed")
        modules = registry_payload.get("modules")
        areas = registry_payload.get("areas")
        if not isinstance(modules, Mapping):
            raise ValueError("registry_modules_malformed")
        if not isinstance(areas, Mapping):
            raise ValueError("registry_areas_malformed")

        requested_area_ids = sorted(
            {
                str(area_id).strip()
                for area_id in (area_ids or [])
                if str(area_id).strip()
            }
        )
        prior_area_ids = {
            str(area_id).strip()
            for area_id, area_entry in areas.items()
            if isinstance(area_entry, Mapping)
            and area_entry.get("module") == slug
            and str(area_id).strip()
        }
        captured_area_ids = sorted(prior_area_ids | set(requested_area_ids))
        prior_area_entries = {
            area_id: copy.deepcopy(areas[area_id])
            for area_id in captured_area_ids
            if area_id in areas
        }
        prior_module_present = slug in modules
        prior_campaign = _capture_campaign_state(resolved_campaign)
        snapshot_identity = {
            "module_slug": slug,
            "registry_path": str(resolved_registry),
            "campaign_path": str(resolved_campaign),
            "requested_area_ids": requested_area_ids,
            "registry_payload": registry_payload,
            "campaign": {
                "exists": prior_campaign["exists"],
                "valid_json_object": prior_campaign["valid_json_object"],
                "payload": prior_campaign["payload"],
                "raw_text": prior_campaign["raw_text"],
            },
        }
        transaction_id = _canonical_hash(snapshot_identity)
        snapshot = {
            "contract_version": ADAPTATION_PUBLICATION_TRANSACTION_CONTRACT_VERSION,
            "transaction_id": transaction_id,
            "module_slug": slug,
            "registry": {
                "path": str(resolved_registry),
                "exists": True,
                "valid_json_object": True,
                "payload": copy.deepcopy(dict(registry_payload)),
                "module_slug": slug,
                "module_present": prior_module_present,
                "module_entry": copy.deepcopy(modules.get(slug))
                if slug in modules
                else None,
                "requested_area_ids": requested_area_ids,
                "area_ids_present": sorted(
                    area_id for area_id in captured_area_ids if area_id in areas
                ),
                "area_entries": prior_area_entries,
                "last_updated_present": "lastUpdated" in registry_payload,
                "last_updated": copy.deepcopy(registry_payload.get("lastUpdated")),
            },
            "campaign": {
                **prior_campaign,
                "available_modules_present": bool(
                    prior_campaign.get("valid_json_object")
                    and isinstance(prior_campaign.get("payload"), Mapping)
                    and "availableModules" in prior_campaign["payload"]
                ),
                "available_modules_valid": bool(
                    prior_campaign.get("valid_json_object")
                    and isinstance(prior_campaign.get("payload"), Mapping)
                    and isinstance(
                        prior_campaign["payload"].get("availableModules"), list
                    )
                ),
                "available_modules": copy.deepcopy(
                    prior_campaign["payload"].get("availableModules")
                )
                if prior_campaign.get("valid_json_object")
                and isinstance(prior_campaign.get("payload"), Mapping)
                and isinstance(prior_campaign["payload"].get("availableModules"), list)
                else None,
            },
        }
        return {
            "status": "success",
            "transaction_id": transaction_id,
            "snapshot": snapshot,
            "metadata": {
                "contract_version": ADAPTATION_PUBLICATION_TRANSACTION_CONTRACT_VERSION,
                "transaction_id": transaction_id,
                "module_slug": slug,
                "registry_path": str(resolved_registry),
                "campaign_path": str(resolved_campaign),
                "registry_file_preexisting": True,
                "module_entry_preexisting": prior_module_present,
                "area_entry_ids_preexisting": sorted(prior_area_ids),
                "campaign_file_preexisting": prior_campaign["exists"],
                "campaign_module_preexisting": bool(
                    prior_campaign.get("valid_json_object")
                    and isinstance(prior_campaign.get("payload"), Mapping)
                    and isinstance(
                        prior_campaign["payload"].get("availableModules"), list
                    )
                    and slug in prior_campaign["payload"]["availableModules"]
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": str(exc) or "adaptation_publication_snapshot_failed",
        }


def _atomic_write_text(path: Path, content: str) -> bool:
    """Restore non-JSON text through a same-directory atomic replace."""
    temporary_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.rollback.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        return True
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except Exception:
                pass
        return False


def _remove_file_atomically(path: Path) -> bool:
    """Remove a transaction-created file through an atomic rename boundary."""
    if not path.exists() and not path.is_symlink():
        return True
    if path.is_dir() and not path.is_symlink():
        return False
    tombstone = path.with_name(f".{path.name}.rollback-delete")
    try:
        if tombstone.exists() or tombstone.is_symlink():
            tombstone.unlink()
        os.replace(str(path), str(tombstone))
        tombstone.unlink(missing_ok=True)
        return not path.exists()
    except Exception:
        try:
            if tombstone.exists() and not path.exists():
                os.replace(str(tombstone), str(path))
        except Exception:
            pass
        return False


def _restore_absent_file(path: Path, label: str) -> Dict[str, Any]:
    """Restore a file that did not exist before the transaction."""
    if not path.exists() and not path.is_symlink():
        return {
            "status": "success",
            "action": "already_absent",
            "changed": False,
            "verified": True,
        }
    removed = _remove_file_atomically(path)
    return {
        "status": "success" if removed else "blocked",
        "action": "removed" if removed else "remove_failed",
        "changed": removed,
        "verified": removed and not path.exists(),
        "reason": "created_file_removed" if removed else f"{label}_remove_failed",
    }


def _restore_full_json_state(state: Mapping[str, Any], label: str) -> Dict[str, Any]:
    """Restore a captured JSON object when targeted state is unusable."""
    path = _resolve_path(Path(str(state.get("path") or "")))
    expected = state.get("payload")
    current = safe_read_json(str(path)) if path.is_file() else None
    if path.is_file() and _strict_equal(expected, current):
        return {
            "status": "success",
            "action": "already_restored",
            "changed": False,
            "verified": True,
        }
    try:
        write_ok = bool(safe_write_json(str(path), copy.deepcopy(expected)))
    except Exception:
        write_ok = False
    if not write_ok:
        return {
            "status": "blocked",
            "action": "restore_failed",
            "changed": False,
            "verified": False,
            "reason": f"{label}_restore_write_failed",
        }
    restored = safe_read_json(str(path)) if path.is_file() else None
    verified = path.is_file() and _strict_equal(expected, restored)
    return {
        "status": "success" if verified else "blocked",
        "action": "restored_full" if verified else "restore_unverified",
        "changed": True,
        "verified": verified,
        "reason": "pre_transaction_state_restored"
        if verified
        else f"{label}_restore_verification_failed",
    }


def _restore_raw_state(state: Mapping[str, Any], label: str) -> Dict[str, Any]:
    """Restore a captured non-JSON file without copying it to public output."""
    path = _resolve_path(Path(str(state.get("path") or "")))
    raw_text = state.get("raw_text")
    if not isinstance(raw_text, str):
        return {
            "status": "blocked",
            "action": "restore_unavailable",
            "changed": False,
            "verified": False,
            "reason": f"{label}_pre_transaction_state_unavailable",
        }
    current_text = None
    try:
        if path.is_file():
            current_text = _read_text(path)
    except Exception:
        current_text = None
    if current_text == raw_text:
        return {
            "status": "success",
            "action": "already_restored",
            "changed": False,
            "verified": True,
        }
    restored = _atomic_write_text(path, raw_text)
    verified = False
    if restored:
        try:
            verified = path.is_file() and _read_text(path) == raw_text
        except Exception:
            verified = False
    return {
        "status": "success" if verified else "blocked",
        "action": "restored" if verified else "restore_unverified",
        "changed": restored,
        "verified": verified,
        "reason": "pre_transaction_state_restored"
        if verified
        else f"{label}_restore_verification_failed",
    }


def _restore_registry_state(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Restore only this transaction's module, areas, and lastUpdated field."""
    path = _resolve_path(Path(str(state.get("path") or "")))
    if state.get("exists") is not True:
        return _restore_absent_file(path, "registry")
    if state.get("valid_json_object") is not True:
        return _restore_full_json_state(state, "registry")

    current = safe_read_json(str(path)) if path.is_file() else None
    if not isinstance(current, Mapping):
        return _restore_full_json_state(state, "registry")
    modules = current.get("modules")
    areas = current.get("areas")
    if not isinstance(modules, Mapping) or not isinstance(areas, Mapping):
        return _restore_full_json_state(state, "registry")

    candidate = copy.deepcopy(dict(current))
    candidate_modules = candidate["modules"]
    candidate_areas = candidate["areas"]
    module_slug = str(state.get("module_slug") or "")
    changed = False
    if state.get("module_present") is True:
        expected_module = state.get("module_entry")
        if not _strict_equal(candidate_modules.get(module_slug), expected_module):
            candidate_modules[module_slug] = copy.deepcopy(expected_module)
            changed = True
    elif module_slug in candidate_modules:
        candidate_modules.pop(module_slug, None)
        changed = True

    prior_area_entries = state.get("area_entries")
    if not isinstance(prior_area_entries, Mapping):
        return _restore_full_json_state(state, "registry")
    prior_area_ids = {
        str(area_id) for area_id in state.get("area_ids_present", [])
    }
    requested_area_ids = {
        str(area_id) for area_id in state.get("requested_area_ids", [])
    }
    for area_id, expected_area in prior_area_entries.items():
        if not _strict_equal(candidate_areas.get(area_id), expected_area):
            candidate_areas[area_id] = copy.deepcopy(expected_area)
            changed = True
    for area_id in requested_area_ids - prior_area_ids:
        if area_id in candidate_areas:
            candidate_areas.pop(area_id, None)
            changed = True
    for area_id, area_entry in list(candidate_areas.items()):
        if (
            isinstance(area_entry, Mapping)
            and area_entry.get("module") == module_slug
            and str(area_id) not in prior_area_ids
        ):
            candidate_areas.pop(area_id, None)
            changed = True

    last_updated_present = state.get("last_updated_present") is True
    if last_updated_present:
        expected_last_updated = state.get("last_updated")
        if not _strict_equal(candidate.get("lastUpdated"), expected_last_updated):
            candidate["lastUpdated"] = copy.deepcopy(expected_last_updated)
            changed = True
    elif "lastUpdated" in candidate:
        candidate.pop("lastUpdated", None)
        changed = True

    if not changed:
        return {
            "status": "success",
            "action": "already_restored",
            "changed": False,
            "verified": True,
        }
    try:
        write_ok = bool(safe_write_json(str(path), candidate))
    except Exception:
        write_ok = False
    if not write_ok:
        return {
            "status": "blocked",
            "action": "restore_failed",
            "changed": False,
            "verified": False,
            "reason": "registry_restore_write_failed",
        }

    restored = safe_read_json(str(path)) if path.is_file() else None
    if not isinstance(restored, Mapping):
        return {
            "status": "blocked",
            "action": "restore_unverified",
            "changed": True,
            "verified": False,
            "reason": "registry_restore_verification_failed",
        }
    restored_modules = restored.get("modules")
    restored_areas = restored.get("areas")
    verified = isinstance(restored_modules, Mapping) and isinstance(
        restored_areas, Mapping
    )
    if verified:
        if state.get("module_present") is True:
            verified = _strict_equal(
                restored_modules.get(module_slug), state.get("module_entry")
            )
        else:
            verified = module_slug not in restored_modules
    if verified:
        verified = all(
            _strict_equal(restored_areas.get(area_id), expected_area)
            for area_id, expected_area in prior_area_entries.items()
        )
    if verified:
        verified = all(
            area_id not in restored_areas
            for area_id in requested_area_ids - prior_area_ids
        ) and all(
            not (
                isinstance(area_entry, Mapping)
                and area_entry.get("module") == module_slug
                and str(area_id) not in prior_area_ids
            )
            for area_id, area_entry in restored_areas.items()
        )
    if verified:
        if last_updated_present:
            verified = _strict_equal(
                restored.get("lastUpdated"), state.get("last_updated")
            )
        else:
            verified = "lastUpdated" not in restored
    return {
        "status": "success" if verified else "blocked",
        "action": "restored" if verified else "restore_unverified",
        "changed": True,
        "verified": verified,
        "reason": "pre_transaction_state_restored"
        if verified
        else "registry_restore_verification_failed",
    }


def _restore_campaign_state(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Restore only the campaign availability field touched by this lane."""
    path = _resolve_path(Path(str(state.get("path") or "")))
    if state.get("exists") is not True:
        return _restore_absent_file(path, "campaign")
    if state.get("valid_json_object") is not True:
        return _restore_raw_state(state, "campaign")
    current = safe_read_json(str(path)) if path.is_file() else None
    if not isinstance(current, Mapping):
        return _restore_full_json_state(state, "campaign")
    if state.get("available_modules_valid") is not True:
        return _restore_full_json_state(state, "campaign")

    candidate = copy.deepcopy(dict(current))
    if state.get("available_modules_present") is True:
        expected_available = state.get("available_modules")
        if not _strict_equal(
            candidate.get("availableModules"), expected_available
        ):
            candidate["availableModules"] = copy.deepcopy(expected_available)
    elif "availableModules" in candidate:
        candidate.pop("availableModules", None)

    if _strict_equal(candidate, current):
        return {
            "status": "success",
            "action": "already_restored",
            "changed": False,
            "verified": True,
        }
    try:
        write_ok = bool(safe_write_json(str(path), candidate))
    except Exception:
        write_ok = False
    if not write_ok:
        return {
            "status": "blocked",
            "action": "restore_failed",
            "changed": False,
            "verified": False,
            "reason": "campaign_restore_write_failed",
        }
    restored = safe_read_json(str(path)) if path.is_file() else None
    verified = isinstance(restored, Mapping) and _strict_equal(
        restored.get("availableModules")
        if state.get("available_modules_present") is True
        else None,
        state.get("available_modules")
        if state.get("available_modules_present") is True
        else None,
    )
    if state.get("available_modules_present") is not True and isinstance(
        restored, Mapping
    ):
        verified = "availableModules" not in restored
    return {
        "status": "success" if verified else "blocked",
        "action": "restored" if verified else "restore_unverified",
        "changed": True,
        "verified": verified,
        "reason": "pre_transaction_state_restored"
        if verified
        else "campaign_restore_verification_failed",
    }


def rollback_adaptation_publication(
    snapshot: Mapping[str, Any],
    *,
    failure_reason: str = "",
) -> Dict[str, Any]:
    """Restore registry and campaign state after a failed publication.

    Campaign visibility is restored first so the campaign never points to a
    module while registry cleanup is still pending. Both files are processed
    even if the first restore fails. Repeating the same call is safe: already
    restored files return a successful no-op result.
    """
    if not isinstance(snapshot, Mapping):
        return {
            "status": "blocked",
            "reason": "rollback_metadata_missing",
            "attempted": False,
            "verified": False,
        }
    if "snapshot" in snapshot and isinstance(snapshot.get("snapshot"), Mapping):
        snapshot = snapshot["snapshot"]
    if snapshot.get("contract_version") != (
        ADAPTATION_PUBLICATION_TRANSACTION_CONTRACT_VERSION
    ):
        return {
            "status": "blocked",
            "reason": "rollback_metadata_malformed",
            "attempted": False,
            "verified": False,
        }
    registry_state = snapshot.get("registry")
    campaign_state = snapshot.get("campaign")
    if not isinstance(registry_state, Mapping) or not isinstance(
        campaign_state, Mapping
    ):
        return {
            "status": "blocked",
            "reason": "rollback_state_missing",
            "attempted": False,
            "verified": False,
        }

    campaign_result = _restore_campaign_state(campaign_state)
    registry_result = _restore_registry_state(registry_state)
    child_results = {
        "campaign": campaign_result,
        "registry": registry_result,
    }
    verified = all(
        result.get("status") == "success" and result.get("verified") is True
        for result in child_results.values()
    )
    changed = any(bool(result.get("changed")) for result in child_results.values())
    idempotent = not changed
    result: Dict[str, Any] = {
        "contract_version": ADAPTATION_PUBLICATION_TRANSACTION_CONTRACT_VERSION,
        "transaction_id": snapshot.get("transaction_id"),
        "module_slug": snapshot.get("module_slug"),
        "status": "success" if verified else "blocked",
        "rollback_status": "rolled_back" if verified else "rollback_incomplete",
        "attempted": True,
        "changed": changed,
        "idempotent": idempotent,
        "verified": verified,
        "campaign": campaign_result,
        "registry": registry_result,
    }
    if failure_reason:
        result["failure_reason"] = str(failure_reason)[:240]
    if not verified:
        result["reason"] = "adaptation_publication_rollback_incomplete"
        error(
            f"TOOLKIT_ADAPTATION: Publication rollback incomplete for {snapshot.get('module_slug')}",
            category="module_ingest",
        )
    else:
        result["reason"] = "adaptation_publication_rolled_back"
    return result


__all__ = [
    "ADAPTATION_PUBLICATION_TRANSACTION_CONTRACT_VERSION",
    "capture_adaptation_publication_snapshot",
    "rollback_adaptation_publication",
]
