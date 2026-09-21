# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Provenance
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded provenance for the explicit LLM adaptation lane. This
module keeps source identity, supplied rights metadata, adaptation status,
model metadata, and world-seed identity consistent across module, report, and
Markdown surfaces. It never determines legal rights or source ownership.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional

from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    ADAPTATION_NOTICE,
    VALID_RIGHTS_CLASSES,
    VALID_RIGHTS_REVIEW_STATUSES,
)
from utils.toolkit_adaptation_config import canonical_monster_generation_enabled
from utils.toolkit_adaptation_world_context import build_world_context_provenance


ADAPTATION_PROVENANCE_CONTRACT_VERSION = "toolkit_adaptation_provenance.v1"
ADAPTATION_PROVENANCE_SCHEMA_VERSION = ADAPTATION_PROVENANCE_CONTRACT_VERSION

ADAPTATION_STATUS_ADAPTED = "adapted"
ADAPTATION_STATUS_BLOCKED = "blocked"
ADAPTATION_STATUS_FAILED = "failed"
ADAPTATION_STATUS_UNKNOWN = "unknown"
VALID_ADAPTATION_STATUSES = (
    ADAPTATION_STATUS_ADAPTED,
    ADAPTATION_STATUS_BLOCKED,
    ADAPTATION_STATUS_FAILED,
    ADAPTATION_STATUS_UNKNOWN,
)

SOURCE_FIDELITY_NOT_APPLICABLE = "not_applicable"
SOURCE_FIDELITY_NON_LITERAL = "non_literal_adaptation"

MAX_PROVENANCE_TEXT_CHARS = 240
MAX_SOURCE_TITLE_CHARS = 400
MAX_RIGHTS_BASIS_CHARS = 500
MAX_MODEL_METADATA_CHARS = 160
MAX_ATTEMPT_ID_CHARS = 96
MAX_SOURCE_PATH_CHARS = 512

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")

MODEL_METADATA_KEYS = (
    "provider",
    "model",
    "model_version",
    "request_id",
    "parameter_profile",
    "temperature",
    "reasoning_effort",
    "verbosity",
    "task_id",
    "prompt_contract",
)


def _ascii_text(value: Any, limit: int = MAX_PROVENANCE_TEXT_CHARS) -> str:
    """Return bounded, redacted, single-line ASCII text."""
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return ""
    text = str(value).replace("\x00", " ")
    text = " ".join(text.split()).strip()
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", text)
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) <= limit:
        return text
    marker = " [truncated]"
    return text[: max(0, limit - len(marker))].rstrip() + marker


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _safe_hash(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if _SHA256_RE.fullmatch(normalized) else None


def _safe_relative_path(value: Any) -> Optional[str]:
    text = _ascii_text(value, MAX_SOURCE_PATH_CHARS)
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or re.match(r"^[A-Za-z]:", text)
    ):
        return None
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    return PurePosixPath(*parts).as_posix()


def _safe_status(value: Any) -> str:
    """Map pipeline statuses to the stable adaptation outcome vocabulary."""
    raw = _ascii_text(value, 64).lower()
    if raw in {"blocked", "failed", "failure", "refused", "error"}:
        return ADAPTATION_STATUS_BLOCKED if raw != "failed" else ADAPTATION_STATUS_FAILED
    if raw in {
        "adapted",
        "success",
        "completed",
        "published",
        "candidate",
        "ready_for_publication",
        "ready_for_registry",
        "passed",
        "pending",
        "building",
        "authoring",
    }:
        return ADAPTATION_STATUS_ADAPTED
    return ADAPTATION_STATUS_UNKNOWN


def _source_mapping(
    dossier: Optional[Mapping[str, Any]],
    provenance: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Merge only the scalar provenance containers used by adaptation code."""
    result: Dict[str, Any] = {}
    for candidate in (dossier, provenance):
        if not isinstance(candidate, Mapping):
            continue
        nested = candidate.get("adaptation_provenance")
        if isinstance(nested, Mapping):
            result.update(dict(nested))
        attempt_metadata = candidate.get("attempt_metadata")
        if isinstance(attempt_metadata, Mapping):
            result.update(dict(attempt_metadata))
        result.update(dict(candidate))
    return result


def _model_metadata(source: Mapping[str, Any]) -> Dict[str, Any]:
    raw = source.get("model_metadata")
    if not isinstance(raw, Mapping):
        raw = {}
    result: Dict[str, Any] = {}
    for key in MODEL_METADATA_KEYS:
        if key not in raw and key in source:
            value = source.get(key)
        else:
            value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            result[key] = value
        elif isinstance(value, str):
            compact = _ascii_text(value, MAX_MODEL_METADATA_CHARS)
            if compact:
                result[key] = compact
    result.setdefault("provider", "not_recorded")
    result.setdefault("model", "not_recorded")
    return result


def build_adaptation_provenance(
    *,
    dossier: Optional[Mapping[str, Any]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    adaptation_status: Any = ADAPTATION_STATUS_ADAPTED,
    world_context: Any = None,
    module_slug: Any = None,
) -> Dict[str, Any]:
    """Build the canonical bounded provenance envelope for an adaptation.

    The supplied rights classification is copied as supplied (after bounded
    text normalization). This function never converts it into a legal ruling.
    Literal source fidelity is always represented as ``not_applicable`` and
    ``non_literal_adaptation`` for this explicit lane.
    """
    source = _source_mapping(dossier, provenance)
    source_hash = _safe_hash(
        _first_value(
            dossier.get("source_hash") if isinstance(dossier, Mapping) else None,
            provenance.get("source_hash") if isinstance(provenance, Mapping) else None,
            source.get("source_hash"),
        )
    )
    rights_value = _first_value(
        source.get("rights_classification"),
        source.get("rights_class"),
        source.get("source_rights_class"),
    )
    rights_classification = _ascii_text(rights_value, 96) or "unknown"
    rights_class = rights_classification
    rights_source = "supplied" if rights_value not in (None, "") else "not_supplied"

    selected_world_context = world_context
    if selected_world_context is None:
        selected_world_context = _first_value(
            source.get("world_context_provenance"),
            source.get("world_context"),
            source,
        )
    world = build_world_context_provenance(selected_world_context)

    result: Dict[str, Any] = {
        "contract_version": ADAPTATION_PROVENANCE_CONTRACT_VERSION,
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "adaptation_status": _safe_status(adaptation_status),
        "adaptation_notice": ADAPTATION_NOTICE,
        "source_title": _ascii_text(source.get("source_title"), MAX_SOURCE_TITLE_CHARS),
        "source_hash": source_hash,
        "source_path": _safe_relative_path(source.get("source_path")),
        "rights_class": rights_class,
        "rights_classification": rights_classification,
        "rights_classification_source": rights_source,
        "rights_basis": _ascii_text(source.get("rights_basis"), MAX_RIGHTS_BASIS_CHARS),
        "rights_review_required": (
            source.get("rights_review_required")
            if isinstance(source.get("rights_review_required"), bool)
            else None
        ),
        "rights_review_status": (
            _ascii_text(source.get("rights_review_status"), 40).lower()
            if _ascii_text(source.get("rights_review_status"), 40).lower()
            in VALID_RIGHTS_REVIEW_STATUSES
            else None
        ),
        "source_fidelity_status": SOURCE_FIDELITY_NOT_APPLICABLE,
        "literal_source_fidelity": SOURCE_FIDELITY_NOT_APPLICABLE,
        "fidelity_claim": SOURCE_FIDELITY_NON_LITERAL,
        "fidelity_explanation": (
            "Literal source fidelity is not applicable; this is a non-literal "
            "NEQ-TTRPG adaptation."
        ),
        "model_metadata": _model_metadata(source),
        "world_context_provenance": world,
        "world_seed_status": world.get("world_seed_status"),
        "world_seed_version": world.get("world_seed_version"),
        "world_seed_hash": world.get("world_seed_hash"),
        "world_context_status": world.get("context_status"),
        "world_context_version": world.get("context_version"),
        "world_context_hash": world.get("context_hash"),
        "context_hash": world.get("context_hash"),
        "world_context_selected_module": world.get("selected_module"),
    }
    # Python-owned operator policy only. Provider/adaptation metadata is never
    # trusted to elevate canonical monster generation.
    if canonical_monster_generation_enabled():
        result["allow_canonical_monster_generation"] = True
    attempt_id = _ascii_text(source.get("attempt_id"), MAX_ATTEMPT_ID_CHARS)
    if attempt_id and _ATTEMPT_ID_RE.fullmatch(attempt_id):
        result["attempt_id"] = attempt_id
    for key in ("attempt_number", "revision_number"):
        value = source.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    safe_module_slug = _ascii_text(module_slug, 140)
    if safe_module_slug:
        result["module_slug"] = safe_module_slug
    return result


normalize_adaptation_provenance = build_adaptation_provenance


def adaptation_provenance_surface_fields(
    provenance: Optional[Mapping[str, Any]] = None,
    *,
    adaptation_status: Any = ADAPTATION_STATUS_ADAPTED,
) -> Dict[str, Any]:
    """Return the bounded scalar fields shared by module and report surfaces."""
    canonical = build_adaptation_provenance(
        provenance=provenance,
        adaptation_status=adaptation_status,
        module_slug=(
            provenance.get("module_slug")
            if isinstance(provenance, Mapping)
            else None
        ),
    )
    fields = {
        "adaptation_provenance": canonical,
        "adaptation_notice": canonical["adaptation_notice"],
        "adaptation_mode": canonical["adaptation_mode"],
        "adaptation_status": canonical["adaptation_status"],
        "source_title": canonical.get("source_title"),
        "source_hash": canonical.get("source_hash"),
        "source_path": canonical.get("source_path"),
        "rights_class": canonical.get("rights_class"),
        "rights_classification": canonical.get("rights_classification"),
        "rights_classification_source": canonical.get("rights_classification_source"),
        "rights_basis": canonical.get("rights_basis"),
        "rights_review_required": canonical.get("rights_review_required"),
        "rights_review_status": canonical.get("rights_review_status"),
        "source_fidelity_status": canonical["source_fidelity_status"],
        "literal_source_fidelity": canonical["literal_source_fidelity"],
        "fidelity_claim": canonical["fidelity_claim"],
        "model_metadata": deepcopy(canonical["model_metadata"]),
        "world_context_provenance": deepcopy(canonical["world_context_provenance"]),
        "world_seed_status": canonical.get("world_seed_status"),
        "world_seed_version": canonical.get("world_seed_version"),
        "world_seed_hash": canonical.get("world_seed_hash"),
        "world_context_status": canonical.get("world_context_status"),
        "world_context_version": canonical.get("world_context_version"),
        "world_context_hash": canonical.get("world_context_hash"),
        "context_hash": canonical.get("context_hash"),
        "world_context_selected_module": canonical.get("world_context_selected_module"),
    }
    for key in ("attempt_id", "attempt_number", "revision_number", "module_slug"):
        if key in canonical:
            fields[key] = canonical[key]
    return fields


build_adaptation_provenance_fields = adaptation_provenance_surface_fields


def validate_adaptation_provenance(
    value: Any,
    *,
    require_source_identity: bool = False,
) -> Dict[str, Any]:
    """Validate the canonical envelope without making legal conclusions."""
    diagnostics: List[str] = []
    if not isinstance(value, Mapping):
        return {"valid": False, "diagnostics": ["provenance_must_be_object"]}
    if value.get("contract_version") != ADAPTATION_PROVENANCE_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    if value.get("adaptation_mode") != ADAPTATION_MODE_LLM:
        diagnostics.append("adaptation_mode_invalid")
    if value.get("adaptation_notice") != ADAPTATION_NOTICE:
        diagnostics.append("adaptation_notice_invalid")
    if value.get("adaptation_status") not in VALID_ADAPTATION_STATUSES:
        diagnostics.append("adaptation_status_invalid")
    if value.get("source_fidelity_status") != SOURCE_FIDELITY_NOT_APPLICABLE:
        diagnostics.append("source_fidelity_status_must_be_not_applicable")
    if value.get("literal_source_fidelity") != SOURCE_FIDELITY_NOT_APPLICABLE:
        diagnostics.append("literal_source_fidelity_must_be_not_applicable")
    if value.get("fidelity_claim") != SOURCE_FIDELITY_NON_LITERAL:
        diagnostics.append("fidelity_claim_must_be_non_literal")

    source_hash = value.get("source_hash")
    if source_hash is not None and _safe_hash(source_hash) is None:
        diagnostics.append("source_hash_invalid")
    if require_source_identity and _safe_hash(source_hash) is None:
        diagnostics.append("source_hash_missing")

    rights_class = value.get("rights_class")
    rights_classification = value.get("rights_classification")
    if not isinstance(rights_class, str) or not rights_class.strip():
        diagnostics.append("rights_class_missing")
    if rights_class != rights_classification:
        diagnostics.append("rights_classification_mismatch")
    if value.get("rights_classification_source") not in {"supplied", "not_supplied"}:
        diagnostics.append("rights_classification_source_invalid")

    model = value.get("model_metadata")
    if not isinstance(model, Mapping):
        diagnostics.append("model_metadata_missing")
    else:
        for key, item in model.items():
            if key not in MODEL_METADATA_KEYS:
                diagnostics.append("model_metadata_key_not_allowlisted")
                break
            if not isinstance(item, (str, int, float)) or isinstance(item, bool):
                diagnostics.append("model_metadata_value_not_scalar")
                break

    world = value.get("world_context_provenance")
    if not isinstance(world, Mapping):
        diagnostics.append("world_context_provenance_missing")
    elif build_world_context_provenance(world) != dict(world):
        diagnostics.append("world_context_provenance_not_canonical")

    if any(key in value for key in ("raw_source", "source_content", "api_key", "password", "secret")):
        diagnostics.append("unsafe_provenance_field")
    return {"valid": not diagnostics, "diagnostics": diagnostics}


def render_adaptation_provenance_markdown(
    provenance: Optional[Mapping[str, Any]] = None,
    *,
    adaptation_status: Any = ADAPTATION_STATUS_ADAPTED,
) -> str:
    """Render bounded provenance lines for the persisted Markdown credits."""
    canonical = build_adaptation_provenance(
        provenance=provenance,
        adaptation_status=adaptation_status,
    )
    lines = [
        "**Adapted for NEQ-TTRPG**",
        "**Adaptation mode:** {}".format(canonical["adaptation_mode"]),
        "**Adaptation status:** {}".format(canonical["adaptation_status"]),
        "**Source title:** {}".format(canonical.get("source_title") or "not_recorded"),
        "**Source hash:** {}".format(canonical.get("source_hash") or "not_recorded"),
        "**Rights classification (supplied):** {}".format(
            canonical.get("rights_classification") or "unknown"
        ),
        "**Source fidelity:** Not applicable; this is a non-literal adaptation.",
    ]
    model = canonical.get("model_metadata") or {}
    model_parts = []
    for key in MODEL_METADATA_KEYS:
        value = model.get(key)
        if value not in (None, ""):
            model_parts.append("{}={}".format(key, _ascii_text(value, 160)))
    lines.append(
        "**Model metadata:** {}".format(
            "; ".join(model_parts) if model_parts else "not_recorded"
        )
    )

    seed_status = canonical.get("world_seed_status") or "unavailable"
    seed_version = canonical.get("world_seed_version")
    seed_hash = canonical.get("world_seed_hash")
    if seed_status == "available" and seed_version and seed_hash:
        lines.append("**World seed provenance:** {} / {}".format(seed_version, seed_hash))
    else:
        lines.append(
            "**World seed provenance:** unavailable; no world-seed grounding is claimed."
        )
    context_status = canonical.get("world_context_status") or "unavailable"
    context_version = canonical.get("world_context_version")
    context_hash = canonical.get("world_context_hash") or canonical.get("context_hash")
    if context_status == "available" and context_version and context_hash:
        lines.append(
            "**World context provenance:** {} / {}".format(
                context_version, context_hash
            )
        )
    else:
        lines.append(
            "**World context provenance:** unavailable; no world-context grounding is claimed."
        )
    return "\n\n".join(lines) + "\n\n"


def load_adaptation_module_provenance(module_dir: Path) -> Optional[Dict[str, Any]]:
    """Load the canonical module provenance, preferring the live context."""
    module_dir = Path(module_dir)
    for filename in ("module_context.json", "module_context_BU.json"):
        payload = safe_read_json(str(module_dir / filename))
        if not isinstance(payload, Mapping):
            continue
        candidate = payload.get("adaptation_provenance")
        if isinstance(candidate, Mapping):
            result = validate_adaptation_provenance(candidate)
            if result["valid"]:
                return deepcopy(dict(candidate))
    return None


def persist_adaptation_module_provenance(
    module_dir: Path,
    provenance: Optional[Mapping[str, Any]] = None,
    *,
    adaptation_status: Any = ADAPTATION_STATUS_ADAPTED,
) -> bool:
    """Atomically add identical bounded metadata to module context files."""
    module_dir = Path(module_dir)
    context_path = module_dir / "module_context.json"
    context = safe_read_json(str(context_path))
    if not isinstance(context, Mapping):
        return False

    canonical = build_adaptation_provenance(
        provenance=provenance,
        adaptation_status=adaptation_status,
        module_slug=module_dir.name,
    )
    if not validate_adaptation_provenance(canonical).get("valid"):
        return False

    targets = [context_path]
    backup_path = module_dir / "module_context_BU.json"
    if backup_path.exists():
        targets.append(backup_path)
    for target in targets:
        payload = safe_read_json(str(target))
        if not isinstance(payload, Mapping):
            return False
        updated = deepcopy(dict(payload))
        updated.update(
            adaptation_provenance_surface_fields(
                canonical,
                adaptation_status=canonical["adaptation_status"],
            )
        )
        if not safe_write_json(str(target), updated):
            return False

    for target in targets:
        written = safe_read_json(str(target))
        if not isinstance(written, Mapping) or written.get("adaptation_provenance") != canonical:
            return False
    return True


update_adaptation_module_provenance = persist_adaptation_module_provenance


__all__ = [
    "ADAPTATION_MODE_LLM",
    "ADAPTATION_NOTICE",
    "ADAPTATION_PROVENANCE_CONTRACT_VERSION",
    "ADAPTATION_PROVENANCE_SCHEMA_VERSION",
    "ADAPTATION_STATUS_ADAPTED",
    "ADAPTATION_STATUS_BLOCKED",
    "ADAPTATION_STATUS_FAILED",
    "ADAPTATION_STATUS_UNKNOWN",
    "MODEL_METADATA_KEYS",
    "SOURCE_FIDELITY_NON_LITERAL",
    "SOURCE_FIDELITY_NOT_APPLICABLE",
    "VALID_ADAPTATION_STATUSES",
    "adaptation_provenance_surface_fields",
    "build_adaptation_provenance",
    "build_adaptation_provenance_fields",
    "load_adaptation_module_provenance",
    "normalize_adaptation_provenance",
    "persist_adaptation_module_provenance",
    "render_adaptation_provenance_markdown",
    "update_adaptation_module_provenance",
    "validate_adaptation_provenance",
]
