# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Module Media Generator Final Report
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from utils.enhanced_logger import warning
from utils.file_operations import safe_read_json, safe_write_json

MODULE_MEDIA_GENERATOR_REPORT_CONTRACT_VERSION = "module_media_generator_report.v1"
MODULE_MEDIA_GENERATOR_REPORT_SOURCE = "module_media_generator"
MODULE_MEDIA_GENERATOR_REPORT_WORKFLOW = MODULE_MEDIA_GENERATOR_REPORT_SOURCE
MODULE_MEDIA_GENERATOR_REPORT_REFRESH_REASON = MODULE_MEDIA_GENERATOR_REPORT_SOURCE

_SUPPORTED_MEDIA_TYPES = {
    "monster": "monsters",
    "npc": "npcs",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_project_root(project_root: Optional[Path | str]) -> Path:
    if project_root is None:
        return Path.cwd()
    return Path(project_root)


def _module_media_dir(project_root: Optional[Path | str], module_name: str, asset_type: str) -> Path:
    root_path = _normalize_project_root(project_root)
    return root_path / "modules" / module_name / "media" / _SUPPORTED_MEDIA_TYPES.get(asset_type, asset_type)


def _normalize_media_asset_id(asset_id: str, asset_type: str) -> str:
    """Normalize module media asset IDs for stable lookup.

    Monster media IDs MUST follow runtime-safe slug rules so stale payloads like
    "will-o'-wisp" resolve to canonical files like "will_o_wisp.jpg".
    """
    normalized = str(asset_id or "").strip()
    if not normalized:
        return ""

    if asset_type != "monster":
        return normalized

    try:
        from updates.update_character_info import normalize_character_name

        normalized = normalize_character_name(normalized)
        return str(normalized or "").strip()
    except Exception:
        fallback = normalized.lower().replace(" ", "_").replace("'", "_")
        return "_".join(segment for segment in fallback.split("_") if segment)


def _first_existing_path(base_dir: Path, candidates: Sequence[str]) -> Optional[Path]:
    for candidate in candidates:
        candidate_path = base_dir / candidate
        if candidate_path.exists():
            return candidate_path
    return None


def _normalize_failure_records(
    generation_failures: Optional[Sequence[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for failure in generation_failures or []:
        if not isinstance(failure, dict):
            continue
        normalized.append(
            {
                "asset_id": str(failure.get("asset_id") or ""),
                "asset_name": str(failure.get("asset_name") or failure.get("asset_id") or ""),
                "asset_type": str(failure.get("asset_type") or ""),
                "phase": str(failure.get("phase") or ""),
                "error": str(failure.get("error") or ""),
            }
        )
    return normalized


def _audit_asset_media(
    project_root: Optional[Path | str],
    module_name: str,
    asset: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    asset_type = str(asset.get("type") or "").strip().lower()
    if asset_type not in _SUPPORTED_MEDIA_TYPES:
        return None

    media_authority = str(asset.get("media_authority") or "").strip()

    asset_id_raw = str(asset.get("id") or "").strip()
    asset_id = _normalize_media_asset_id(asset_id_raw, asset_type)
    if not asset_id:
        return None

    asset_name = str(asset.get("name") or asset_id).strip() or asset_id

    # When an NPC row delegates media authority to a monster, check the
    # monster media folder and mark the entry as complete/skipped for MMG.
    is_delegated = bool(media_authority) and media_authority != "self"
    effective_type = "monster" if is_delegated else asset_type
    media_dir = _module_media_dir(project_root, module_name, effective_type)
    image_path = _first_existing_path(media_dir, [f"{asset_id}.jpg", f"{asset_id}.png"])
    thumbnail_path = _first_existing_path(
        media_dir,
        [f"{asset_id}_thumb.jpg", f"{asset_id}_thumb.png"],
    )
    video_path = media_dir / f"{asset_id}_video.mp4"

    has_image = image_path is not None
    has_thumbnail = thumbnail_path is not None
    has_video = video_path.exists()
    missing_fields = []
    if not has_image:
        missing_fields.append("image")
    if not has_thumbnail:
        missing_fields.append("thumbnail")

    result: Dict[str, Any] = {
        "id": asset_id,
        "name": asset_name,
        "type": asset_type,
        "has_image": has_image,
        "has_thumbnail": has_thumbnail,
        "has_video": has_video,
        "image_path": str(image_path) if image_path else None,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "missing_fields": missing_fields,
        "complete": not missing_fields,
    }

    if is_delegated:
        result["authority_delegated"] = True
        # Delegated entries are considered complete even without local media.
        result["complete"] = True
        result["missing_fields"] = []

    return result


def build_module_media_generator_report(
    module_name: str,
    assets: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    project_root: Optional[Path | str] = None,
    generation_failures: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    normalized_assets = [asset for asset in assets or [] if isinstance(asset, dict)]
    normalized_failures = _normalize_failure_records(generation_failures)
    asset_audits: List[Dict[str, Any]] = []

    for asset in normalized_assets:
        audit = _audit_asset_media(project_root, module_name, asset)
        if audit is not None:
            asset_audits.append(audit)

    # Canonical same-slug actor authority: if both monster and npc appear for
    # the same slug, keep the monster audit row and drop the duplicate npc row.
    canonical_audits: List[Dict[str, Any]] = []
    grouped_by_slug: Dict[str, List[Dict[str, Any]]] = {}
    for audit in asset_audits:
        slug = str(audit.get("id") or "").strip()
        grouped_by_slug.setdefault(slug, []).append(audit)

    for slug, grouped_rows in grouped_by_slug.items():
        if not slug:
            canonical_audits.extend(grouped_rows)
            continue
        monster_rows = [row for row in grouped_rows if str(row.get("type") or "") == "monster"]
        if monster_rows:
            canonical_audits.append(monster_rows[0])
        else:
            canonical_audits.extend(grouped_rows)

    asset_audits = canonical_audits

    missing_assets = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "type": entry["type"],
            "missing_fields": list(entry.get("missing_fields") or []),
        }
        for entry in asset_audits
        if entry.get("missing_fields") and not entry.get("authority_delegated")
    ]

    missing_count = len(missing_assets)
    complete_assets = sum(1 for entry in asset_audits if entry.get("complete"))
    if missing_count > 0:
        status = "fail"
    elif normalized_failures:
        status = "degraded"
    else:
        status = "pass"

    report: Dict[str, Any] = {
        "module_slug": module_name,
        "source": MODULE_MEDIA_GENERATOR_REPORT_SOURCE,
        "contract": MODULE_MEDIA_GENERATOR_REPORT_CONTRACT_VERSION,
        "authoritative": True,
        "status": status,
        "freshness_state": "current",
        "generated_at": _utc_now_iso(),
        "report_freshness": {
            "state": "current",
            "authoritative": True,
            "written_at": _utc_now_iso(),
            "phase": "final",
            "workflow": MODULE_MEDIA_GENERATOR_REPORT_WORKFLOW,
            "refresh_reason": MODULE_MEDIA_GENERATOR_REPORT_REFRESH_REASON,
            "contract": MODULE_MEDIA_GENERATOR_REPORT_CONTRACT_VERSION,
            "stale_reason": None,
        },
        "total_assets": len(asset_audits),
        "complete_assets": complete_assets,
        "missing_count": missing_count,
        "missing_assets": missing_assets,
        "asset_audits": asset_audits,
        "generation_failures": normalized_failures,
        "module_media_policy": {
            "module_local_only": True,
            "static_fallback_counts": False,
            "completion_rule": "image_and_thumbnail",
        },
    }

    return report


def write_module_media_generator_report(
    module_name: str,
    assets: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    project_root: Optional[Path | str] = None,
    generation_failures: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
    root_path = _normalize_project_root(project_root)
    report = build_module_media_generator_report(
        module_name,
        assets,
        project_root=root_path,
        generation_failures=generation_failures,
    )
    report_path = root_path / "modules" / module_name / "module_media_generator_report.json"
    report["report_path"] = str(report_path)

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_result = safe_write_json(str(report_path), report)
        if write_result is False:
            warning(
                f"Failed to persist module media report for {module_name} at {report_path}",
                category="module_loading",
            )
            report["report_write_error"] = True
    except Exception as exc:
        warning(
            f"Failed to persist module media report for {module_name}: {exc}",
            category="module_loading",
        )
        report["report_write_error"] = True

    return report


def load_module_media_generator_report(
    module_name: str,
    *,
    project_root: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    report_path = _normalize_project_root(project_root) / "modules" / module_name / "module_media_generator_report.json"
    if not report_path.exists():
        return None

    try:
        payload = safe_read_json(str(report_path))
    except Exception as exc:
        warning(
            f"Failed to load module media report for {module_name}: {exc}",
            category="module_loading",
        )
        return None

    return payload if isinstance(payload, dict) else None


def is_module_media_generator_report_authoritative(report_data: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(report_data, dict):
        return False

    report_freshness = report_data.get("report_freshness")
    if not isinstance(report_freshness, dict):
        return False

    freshness_state = str(
        report_freshness.get("state") or report_data.get("freshness_state") or ""
    ).strip().lower()
    phase = str(report_freshness.get("phase") or "").strip().lower()
    workflow = str(report_freshness.get("workflow") or "").strip().lower()
    contract = str(report_freshness.get("contract") or report_data.get("contract") or "").strip().lower()
    source = str(report_data.get("source") or "").strip().lower()

    return (
        bool(report_freshness.get("authoritative"))
        and freshness_state == "current"
        and phase == "final"
        and workflow == MODULE_MEDIA_GENERATOR_REPORT_WORKFLOW
        and contract == MODULE_MEDIA_GENERATOR_REPORT_CONTRACT_VERSION
        and source == MODULE_MEDIA_GENERATOR_REPORT_SOURCE
    )


def summarize_module_media_generator_report(
    report_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not is_module_media_generator_report_authoritative(report_data):
        return {}

    normalized_data = report_data or {}
    missing_assets = normalized_data.get("missing_assets")
    if not isinstance(missing_assets, list):
        missing_assets = []

    missing_count = int(normalized_data.get("missing_count") or len(missing_assets))
    summary: Dict[str, Any] = {
        "authoritative": True,
        "status": str(normalized_data.get("status") or "pass").strip().lower(),
        "missing_count": missing_count,
        "missing_assets": [
            {
                "id": str(asset.get("id") or ""),
                "name": str(asset.get("name") or asset.get("id") or ""),
                "type": str(asset.get("type") or ""),
                "missing_fields": list(asset.get("missing_fields") or []),
            }
            for asset in missing_assets
            if isinstance(asset, dict)
        ],
    }

    if missing_count > 0:
        summary.update(
            {
                "media_generator_needed": True,
                "brief_failure": "Publication blocked: missing media",
                "media_handoff": {
                    "build_outcome": "needs_module_media_generator",
                    "next_step": "Module Builder -> Module Media Generator",
                    "message": (
                        "Module Media Generator final audit still reports missing module-local media."
                    ),
                    "media_debt_count": missing_count,
                    "media_debt_slugs": [
                        str(asset.get("id") or "")
                        for asset in summary["missing_assets"]
                        if asset.get("id")
                    ],
                    "source": MODULE_MEDIA_GENERATOR_REPORT_SOURCE,
                    "contract": MODULE_MEDIA_GENERATOR_REPORT_CONTRACT_VERSION,
                },
            }
        )
    else:
        summary["media_generator_needed"] = False

    return summary
