# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - LLM Adaptation Campaign Availability
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Python-owned, provider-free campaign availability synchronization for the
explicit LLM adaptation publication lane. The helper changes only the
campaign available-module index, writes it atomically, and verifies the
persisted visibility after the write.

This helper does not change mechanical state, world narrative state, party
state, registry entries, or module artifacts. The adaptation publication
transaction captures campaign state before registry publication and restores
it if a later publication step fails.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from utils.file_operations import safe_read_json, safe_write_json


ADAPTATION_CAMPAIGN_SYNC_CONTRACT_VERSION = "toolkit_adaptation_campaign_sync.v1"
DEFAULT_CAMPAIGN_RELATIVE_PATH = "modules/campaign.json"
DEFAULT_REGISTRY_RELATIVE_PATH = "modules/world_registry.json"
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_INACTIVE_CAMPAIGN_STATUSES = frozenset({"inactive", "closed", "archived"})


def _resolve_path(path: Optional[Path], default_relative_path: str) -> Path:
    """Resolve an explicit or repository-relative runtime state path."""
    candidate = Path(path) if path is not None else Path(default_relative_path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _validate_module_slug(value: Any) -> str:
    """Validate the Python-owned module identity before touching state."""
    if not isinstance(value, str) or not _MODULE_SLUG_RE.fullmatch(value):
        raise ValueError("module_slug is not path-safe")
    return value


def _utc_now_iso() -> str:
    """Return a second-precision UTC timestamp for optional diagnostics."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _base_result(
    module_slug: str,
    campaign_path: Path,
    registry_path: Path,
    require_active_campaign: bool,
) -> Dict[str, Any]:
    """Build the bounded campaign synchronization result envelope."""
    return {
        "contract_version": ADAPTATION_CAMPAIGN_SYNC_CONTRACT_VERSION,
        "status": "blocked",
        "module_slug": module_slug,
        "campaign_path": str(campaign_path),
        "registry_path": str(registry_path),
        "campaign_present": False,
        "active_campaign": None,
        "campaign_sync_required": bool(require_active_campaign),
        "campaign_visibility_verified": False,
        "python_authoritative": True,
        "write": {"status": "not_attempted", "atomic": True},
        "verification": {
            "status": "not_attempted",
            "visible": False,
        },
    }


def _load_campaign_file(path: Path) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """Load campaign state and distinguish absent, malformed, and valid data."""
    if not path.exists():
        return "missing", None, "campaign_missing"
    if not path.is_file() or path.is_symlink():
        return "malformed", None, "campaign_not_regular_file"
    try:
        payload = safe_read_json(str(path))
    except Exception:
        return "malformed", None, "campaign_malformed"
    if not isinstance(payload, Mapping):
        return "malformed", None, "campaign_malformed"
    return "available", dict(payload), ""


def _campaign_activity(campaign: Mapping[str, Any]) -> Tuple[str, str]:
    """Resolve explicit campaign activity markers without guessing state."""
    for key in ("active", "activeCampaign", "active_campaign"):
        if key not in campaign:
            continue
        marker = campaign.get(key)
        if not isinstance(marker, bool):
            return "malformed", f"campaign_{key}_malformed"
        if marker is False:
            return "inactive", "no_active_campaign"

    status = campaign.get("status")
    if status is not None:
        if not isinstance(status, str):
            return "malformed", "campaign_status_malformed"
        if status.strip().lower() in _INACTIVE_CAMPAIGN_STATUSES:
            return "inactive", "no_active_campaign"

    return "active", ""


def _available_modules(campaign: Mapping[str, Any]) -> Tuple[Optional[list], str]:
    """Return the canonical camel-case campaign availability list."""
    available = campaign.get("availableModules")
    if not isinstance(available, list):
        return None, "campaign_available_modules_malformed"
    if any(not isinstance(module, str) for module in available):
        return None, "campaign_available_modules_malformed"
    return list(available), ""


def _verify_published_registry_module(
    registry_path: Path,
    module_slug: str,
) -> Dict[str, Any]:
    """Confirm the registry still contains the module before campaign writes."""
    if not registry_path.is_file():
        return {
            "status": "blocked",
            "verified": False,
            "reason": "registry_missing",
        }
    try:
        registry = safe_read_json(str(registry_path))
    except Exception:
        return {
            "status": "blocked",
            "verified": False,
            "reason": "registry_malformed",
        }
    if not isinstance(registry, Mapping):
        return {
            "status": "blocked",
            "verified": False,
            "reason": "registry_malformed",
        }
    modules = registry.get("modules")
    if not isinstance(modules, Mapping):
        return {
            "status": "blocked",
            "verified": False,
            "reason": "registry_modules_malformed",
        }
    module_entry = modules.get(module_slug)
    if not isinstance(module_entry, Mapping):
        return {
            "status": "blocked",
            "verified": False,
            "reason": "registry_module_not_published",
        }
    return {
        "status": "success",
        "verified": True,
        "module_slug": module_slug,
    }


def _verify_campaign_visibility(
    campaign_path: Path,
    module_slug: str,
) -> Dict[str, Any]:
    """Re-read campaign state and verify exact module visibility."""
    state, campaign, reason = _load_campaign_file(campaign_path)
    if state != "available" or campaign is None:
        return {
            "status": "blocked",
            "visible": False,
            "reason": reason or "campaign_post_write_read_failed",
        }
    activity, activity_reason = _campaign_activity(campaign)
    if activity != "active":
        return {
            "status": "blocked",
            "visible": False,
            "reason": activity_reason or "campaign_post_write_not_active",
        }
    available, available_reason = _available_modules(campaign)
    if available is None:
        return {
            "status": "blocked",
            "visible": False,
            "reason": available_reason,
        }
    visible = module_slug in available
    return {
        "status": "success" if visible else "blocked",
        "visible": visible,
        "reason": "campaign_module_visible"
        if visible
        else "campaign_module_visibility_missing",
        "available_modules_count": len(available),
    }


def synchronize_adaptation_campaign_module(
    module_slug: str,
    *,
    campaign_path: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    require_active_campaign: bool = False,
) -> Dict[str, Any]:
    """Synchronize and verify one published module in campaign availability.

    A missing campaign file means there is no active campaign by default and
    returns an explicit deferred result. Callers that have independently
    established that an active campaign is required can pass
    ``require_active_campaign=True``; a missing campaign then fails closed.
    Existing campaign files must be valid and use the repository's
    ``availableModules`` list. Only that list is changed.
    """
    resolved_campaign_path = _resolve_path(campaign_path, DEFAULT_CAMPAIGN_RELATIVE_PATH)
    resolved_registry_path = _resolve_path(registry_path, DEFAULT_REGISTRY_RELATIVE_PATH)
    raw_slug = str(module_slug or "")
    result = _base_result(
        raw_slug,
        resolved_campaign_path,
        resolved_registry_path,
        require_active_campaign,
    )

    try:
        slug = _validate_module_slug(module_slug)
    except Exception as exc:
        result["reason"] = str(exc) or "module_slug_invalid"
        return result
    result["module_slug"] = slug

    campaign_state, campaign, campaign_reason = _load_campaign_file(
        resolved_campaign_path
    )
    if campaign_state == "missing":
        if require_active_campaign:
            result.update(
                {
                    "status": "blocked",
                    "reason": "campaign_missing",
                    "campaign_sync_required": True,
                    "verification": {
                        "status": "blocked",
                        "visible": False,
                        "reason": "campaign_missing",
                    },
                }
            )
            return result
        result.update(
            {
                "status": "deferred",
                "reason": "no_active_campaign",
                "campaign_present": False,
                "active_campaign": False,
                "campaign_sync_required": False,
                "verification": {
                    "status": "deferred",
                    "visible": False,
                    "reason": "no_active_campaign",
                },
            }
        )
        return result

    result["campaign_present"] = True
    if campaign_state != "available" or campaign is None:
        result.update(
            {
                "status": "blocked",
                "reason": campaign_reason or "campaign_malformed",
                "campaign_sync_required": True,
                "verification": {
                    "status": "blocked",
                    "visible": False,
                    "reason": campaign_reason or "campaign_malformed",
                },
            }
        )
        return result

    activity, activity_reason = _campaign_activity(campaign)
    if activity == "inactive":
        if require_active_campaign:
            result.update(
                {
                    "status": "blocked",
                    "reason": "no_active_campaign",
                    "active_campaign": False,
                    "campaign_sync_required": True,
                    "verification": {
                        "status": "blocked",
                        "visible": False,
                        "reason": "no_active_campaign",
                    },
                }
            )
            return result
        result.update(
            {
                "status": "deferred",
                "reason": "no_active_campaign",
                "active_campaign": False,
                "campaign_sync_required": False,
                "verification": {
                    "status": "deferred",
                    "visible": False,
                    "reason": "no_active_campaign",
                },
            }
        )
        return result
    if activity != "active":
        result.update(
            {
                "status": "blocked",
                "reason": activity_reason or "campaign_activity_malformed",
                "campaign_sync_required": True,
                "verification": {
                    "status": "blocked",
                    "visible": False,
                    "reason": activity_reason or "campaign_activity_malformed",
                },
            }
        )
        return result

    result.update(
        {
            "active_campaign": True,
            "campaign_sync_required": True,
        }
    )
    available, available_reason = _available_modules(campaign)
    if available is None:
        result.update(
            {
                "status": "blocked",
                "reason": available_reason,
                "verification": {
                    "status": "blocked",
                    "visible": False,
                    "reason": available_reason,
                },
            }
        )
        return result

    registry_verification = _verify_published_registry_module(
        resolved_registry_path,
        slug,
    )
    result["registry_verification"] = registry_verification
    if registry_verification.get("status") != "success":
        result.update(
            {
                "status": "blocked",
                "reason": "campaign_sync_registry_not_verified",
                "verification": {
                    "status": "blocked",
                    "visible": False,
                    "reason": registry_verification.get(
                        "reason", "registry_not_verified"
                    ),
                },
            }
        )
        return result

    changed = slug not in available
    if changed:
        candidate = copy.deepcopy(campaign)
        candidate["availableModules"] = list(available) + [slug]
        try:
            write_ok = bool(safe_write_json(str(resolved_campaign_path), candidate))
        except Exception:
            write_ok = False
        if not write_ok:
            result.update(
                {
                    "status": "blocked",
                    "reason": "campaign_write_failed",
                    "write": {"status": "failed", "atomic": True},
                    "verification": {
                        "status": "blocked",
                        "visible": False,
                        "reason": "campaign_write_failed",
                    },
                }
            )
            return result
        result["write"] = {
            "status": "success",
            "atomic": True,
            "changed": True,
        }
    else:
        result["write"] = {
            "status": "not_required",
            "atomic": True,
            "changed": False,
        }

    verification = _verify_campaign_visibility(resolved_campaign_path, slug)
    result["verification"] = verification
    if verification.get("status") != "success" or verification.get("visible") is not True:
        result.update(
            {
                "status": "blocked",
                "reason": "campaign_post_write_verification_failed",
                "campaign_visibility_verified": False,
            }
        )
        return result

    result.update(
        {
            "status": "success",
            "reason": "campaign_module_available_and_verified",
            "campaign_visibility_verified": True,
            "verified_at": _utc_now_iso(),
        }
    )
    return result


__all__ = [
    "ADAPTATION_CAMPAIGN_SYNC_CONTRACT_VERSION",
    "DEFAULT_CAMPAIGN_RELATIVE_PATH",
    "DEFAULT_REGISTRY_RELATIVE_PATH",
    "synchronize_adaptation_campaign_module",
]
