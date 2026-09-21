# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Adaptation Monster Guardrail
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free orchestration for the adaptation dossier's encounter
adversaries.  This module only extracts bounded source data and delegates
artifact resolution and encounter binding to the accurate-ingest helper.
It does not call a provider, perform closure, or write files.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from utils.file_operations import safe_read_json, safe_write_json
from utils.module_monster_authority import (
    find_reusable_monster_path,
    load_monster_compendium_lookup,
)
from utils.monster_reference_closure import normalize_monster_name


ADAPTATION_MONSTER_GUARDRAIL_VERSION = (
    "toolkit_adaptation_monster_guardrail.v1"
)
# Public alias for callers that use the more explicit report terminology.
ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION = (
    ADAPTATION_MONSTER_GUARDRAIL_VERSION
)

MAX_ADAPTATION_ENCOUNTERS = 64
MAX_ADAPTATION_ADVERSARIES = 128
MAX_ADVERSARY_CHARS = 160
MAX_SEED_TEXT_CHARS = 240
MAX_SEED_LIST_ITEMS = 16
MAX_DIAGNOSTICS = 24
MAX_RESOLUTION_DIAGNOSTICS = 128
MAX_LOCATION_MONSTER_ENTRIES = 128
MAX_CANONICAL_MONSTER_VOCABULARY = 256
MAX_NORMALIZED_MONSTER_RECORDS = 128
MAX_EXCLUDED_MONSTER_RECORDS = 128
MAX_MONSTER_ENTRY_CHARS = 240
MAX_MONSTER_PROSE_CHARS = 240
MAX_QUANTITY_CHARS = 32
MAX_ARTIFACT_PATH_CHARS = 320
MAX_ENCOUNTER_CONTEXTS = 8
MAX_MATERIALIZATION_ATTEMPTS = 8
MAX_SOURCE_MODULE_MONSTER_SCAN = 128
DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS = 120
MAX_ADAPTATION_AREA_FILES = 64
MAX_ADAPTATION_LOCATION_REPORTS = 128
MAX_ADAPTATION_PROSE_NOTES = 24
ADAPTATION_SOURCE_RECONCILIATION_VERSION = (
    "toolkit_adaptation_source_reconciliation.v1"
)
MAX_SOURCE_RECONCILIATION_CANDIDATES = 32
MAX_SOURCE_RECONCILIATION_DIAGNOSTICS = 24
MAX_RESOLUTION_IDENTITY_VARIANTS = 4
ADAPTATION_MONSTER_IDENTITY_REGISTRY_VERSION = (
    "toolkit_adaptation_monster_identity_registry.v1"
)
MAX_IDENTITY_REGISTRY_ENTRIES = 256
MAX_IDENTITY_REGISTRY_ALIASES = 8
MAX_IDENTITY_REGISTRY_PROVENANCE = 32
MAX_IDENTITY_REGISTRY_LOCATIONS = 32
MAX_IDENTITY_REGISTRY_ENCOUNTERS = 32
MAX_IDENTITY_REGISTRY_QUANTITIES = 32

# Keep parity with the accurate-ingest materialization and module-authority
# contracts.  Empty strings are treated as insufficient by the existing
# hydration helper even though the adaptation report also documents the
# required fields explicitly.
ADAPTATION_MONSTER_REQUIRED_FIELDS = (
    "size",
    "alignment",
    "armorClass",
)

_WHITESPACE_RE = re.compile(r"\s+")
_SAFE_MISSING_MODULE_DIR = os.path.join(
    "tmp", "adaptation_monster_guardrail_missing"
)


def _safe_text(value: Any, limit: int) -> str:
    """Return bounded, whitespace-normalized ASCII text."""
    text = str(value).replace("\x00", " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    text = "".join(
        character if 32 <= ord(character) < 127 else " "
        for character in text
    )
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(
    code: str,
    message: str,
    *,
    encounter_index: Optional[int] = None,
    adversary: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one bounded diagnostic without copying arbitrary input."""
    result: Dict[str, Any] = {
        "code": _safe_text(code, 96),
        "message": _safe_text(message, MAX_SEED_TEXT_CHARS),
    }
    if encounter_index is not None:
        result["encounter_index"] = encounter_index
    if adversary:
        result["adversary"] = _safe_text(adversary, MAX_ADVERSARY_CHARS)
    return result


def _missing_artifact_fields(artifact_path: Any) -> List[str]:
    """Return required fields missing from one candidate artifact.

    This is read-only and intentionally mirrors the existing materialization
    contract.  It is used only to make unresolved adaptation diagnostics
    actionable; it never creates or substitutes an artifact identity.
    """
    try:
        path = os.fspath(artifact_path) if artifact_path else ""
    except TypeError:
        path = ""
    if not path:
        return list(ADAPTATION_MONSTER_REQUIRED_FIELDS)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, Mapping):
        return list(ADAPTATION_MONSTER_REQUIRED_FIELDS)
    return [
        field
        for field in ADAPTATION_MONSTER_REQUIRED_FIELDS
        if payload.get(field) in (None, "")
    ]


def _encounter_contexts(
    seeds: Sequence[Mapping[str, Any]],
    reference: str,
) -> List[Dict[str, Any]]:
    """Return bounded source/encounter context for one source reference."""
    contexts: List[Dict[str, Any]] = []
    for encounter_index, seed in enumerate(seeds):
        raw_adversaries = seed.get("adversaries", [])
        if not isinstance(raw_adversaries, Sequence) or isinstance(
            raw_adversaries, (str, bytes)
        ):
            continue
        if not any(
            _adaptation_identity_matches(reference, value)
            for value in raw_adversaries
            if isinstance(value, str)
        ):
            continue
        context: Dict[str, Any] = {"encounter_index": encounter_index}
        for field in ("name", "location", "source_basis", "setup", "stakes"):
            value = seed.get(field)
            if isinstance(value, str) and value.strip():
                context[field] = _safe_text(value, MAX_SEED_TEXT_CHARS)
        contexts.append(context)
        if len(contexts) >= MAX_ENCOUNTER_CONTEXTS:
            break
    return contexts


def _adversary_key(value: str) -> str:
    """Return a stable case-insensitive identity key for deduplication."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _adaptation_identity_matches(left: Any, right: Any) -> bool:
    """Return whether two adaptation labels share a bounded identity variant."""
    left_identity = _adaptation_identity_variants(left)
    right_identity = _adaptation_identity_variants(right)
    left_variants = {
        value for value in left_identity.get("variants", [])
        if isinstance(value, str) and value
    }
    right_variants = {
        value for value in right_identity.get("variants", [])
        if isinstance(value, str) and value
    }
    return bool(left_variants.intersection(right_variants))


def _adaptation_identity_variants(value: Any) -> Dict[str, Any]:
    """Return bounded identity variants for one adaptation source label.

    This helper intentionally performs only mechanical normalization.  The
    bounded source label is retained separately for provenance, while the
    ordered variants provide exact-first and folded lookup keys for later
    adaptation-only resolution.  It does not interpret descriptive prose or
    classify broad creature words.
    """
    raw_label = _safe_text(value, MAX_ADVERSARY_CHARS)
    raw_key = _adversary_key(raw_label)
    variants: List[str] = []

    def _append(candidate: str) -> None:
        candidate_key = _adversary_key(candidate)
        if candidate_key and candidate_key not in variants:
            variants.append(candidate_key)

    _append(raw_key)
    quantity_stripped, quantity_text, quantity_value = _strip_quantity_prefix(raw_key)
    _append(quantity_stripped)
    stripped_tokens = _monster_tokens(quantity_stripped)
    for form in _singular_plural_forms(stripped_tokens):
        _append(" ".join(form))

    return {
        "raw_label": raw_label,
        "raw_key": raw_key,
        "quantity_prefix": _safe_text(quantity_text, MAX_QUANTITY_CHARS),
        "quantity_value": quantity_value,
        "variants": variants[:4],
    }


def _adaptation_canonical_identity_key(identity: Mapping[str, Any]) -> str:
    """Select the singular folded key without broad semantic inference."""
    variants = [
        value for value in identity.get("variants", [])
        if isinstance(value, str) and value
    ]
    if not variants:
        return ""
    raw_key = identity.get("raw_key", variants[0])
    quantity_prefix = identity.get("quantity_prefix", "")
    # A quantity-qualified label always folds to the singular form of the
    # quantity-stripped phrase.  For an ordinary plural, the helper's second
    # variant is the singular form; for an ordinary singular the raw key is
    # already canonical.
    if quantity_prefix and len(variants) > 1:
        stripped = variants[1]
        if stripped.endswith(("s", "es", "ies")):
            forms = _singular_plural_forms(stripped.split())
            return " ".join(forms[1]) if len(forms) > 1 else stripped
        return stripped
    forms = _singular_plural_forms(str(raw_key).split())
    if str(raw_key).endswith(("s", "es", "ies")) and len(forms) > 1:
        return " ".join(forms[1])
    return str(raw_key)


def _adaptation_identity_display_name(identity_key: str) -> str:
    """Build a bounded builder-facing name from a normalized identity key."""
    return " ".join(part.capitalize() for part in identity_key.split())


def _payload_matches_adaptation_identity(
    payload: Optional[Mapping[str, Any]],
    identity: Mapping[str, Any],
    canonical_name: str,
) -> bool:
    """Match a bounded raw/folded identity without accepting substitutions."""
    if not isinstance(payload, Mapping):
        return False
    payload_name = payload.get("name")
    if payload_name in (None, ""):
        return True
    if not isinstance(payload_name, str):
        return False
    return _canonical_monster_slug(payload_name) in _adaptation_identity_slugs(
        identity, canonical_name
    )


def _adaptation_identity_slugs(
    identity: Mapping[str, Any], canonical_name: Any = ""
) -> set[str]:
    """Return the bounded filename identities accepted for one source label."""
    values = list(identity.get("variants", []))
    if canonical_name:
        values.append(canonical_name)
    return {
        _canonical_monster_slug(value)
        for value in values
        if isinstance(value, str) and value
    }


def _canonical_monster_slug(value: Any) -> str:
    """Return the shared canonical monster filename slug without providers."""
    try:
        # Adaptation staging must use the same slug contract as final closure.
        # In particular, closure removes apostrophes rather than converting
        # them to an extra underscore ("Vey's" -> "veys").
        return normalize_monster_name(str(value or ""))
    except Exception:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _bounded_path(value: Any) -> str:
    """Return a bounded filesystem diagnostic path."""
    return _safe_text(value, MAX_ARTIFACT_PATH_CHARS)


def _load_monster_artifact(path: Any) -> Tuple[Optional[Dict[str, Any]], str, List[str]]:
    """Load one candidate and report deterministic schema/read failures."""
    try:
        candidate = os.fspath(path) if path else ""
    except TypeError:
        candidate = ""
    if not candidate:
        return None, "missing_path", []
    if not os.path.isfile(candidate):
        return None, "file_not_found", []
    try:
        with open(candidate, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, TypeError):
        return None, "read_error", []
    except ValueError:
        return None, "invalid_json", []
    if not isinstance(payload, dict):
        return None, "invalid_payload", []
    missing = [
        field
        for field in ADAPTATION_MONSTER_REQUIRED_FIELDS
        if payload.get(field) in (None, "")
    ]
    if missing:
        return payload, "missing_required_fields", missing
    return payload, "schema_sufficient", []


def _payload_matches_canonical_identity(
    payload: Optional[Mapping[str, Any]], canonical_name: str
) -> bool:
    """Reject named reusable/generated payloads that substitute identity."""
    if not isinstance(payload, Mapping):
        return False
    payload_name = payload.get("name")
    if payload_name in (None, ""):
        return True
    return (
        isinstance(payload_name, str)
        and _canonical_monster_slug(payload_name)
        == _canonical_monster_slug(canonical_name)
    )


def _monster_candidate_path(root: Any, canonical_slug: str) -> str:
    """Resolve a module root or monsters directory to one canonical path."""
    root_path = os.fspath(root) if root else ""
    if os.path.basename(os.path.normpath(root_path)) == "monsters":
        monsters_dir = root_path
    else:
        monsters_dir = os.path.join(root_path, "monsters")
    return os.path.join(monsters_dir, f"{canonical_slug}.json")


MAX_REUSABLE_ROOT_CANDIDATES = 32
MAX_REUSABLE_ROOT_DEPTH = 5


def _normalize_reusable_root_candidates(root: Any) -> List[str]:
    """Return explicit reusable roots, including safe contained module roots.

    A caller may supply a wrapper directory around a module or a staging
    revision.  We only descend that explicitly supplied directory, never a
    repository-wide root, and only accept directories carrying a module/staging
    marker alongside ``monsters/``.  Symlinks are not followed.
    """
    try:
        supplied = os.path.abspath(os.fspath(root)) if root else ""
    except TypeError:
        return []
    if not supplied or not os.path.isdir(supplied) or os.path.islink(supplied):
        return []
    if os.path.isdir(os.path.join(supplied, "monsters")):
        return [supplied]

    candidates: List[Tuple[int, str]] = []
    for current, dirs, _files in os.walk(supplied, topdown=True, followlinks=False):
        current_path = os.path.abspath(current)
        try:
            relative = os.path.relpath(current_path, supplied)
            depth = 0 if relative == "." else len(Path(relative).parts)
        except (OSError, ValueError):
            dirs[:] = []
            continue
        if depth >= MAX_REUSABLE_ROOT_DEPTH:
            dirs[:] = []
        dirs[:] = sorted(
            directory for directory in dirs
            if not os.path.islink(os.path.join(current_path, directory))
        )
        monsters_dir = os.path.join(current_path, "monsters")
        if not os.path.isdir(monsters_dir):
            continue
        marker_names = {
            "staging_metadata.json",
            "module_context.json",
            "module_context_BU.json",
            "module_plot.json",
            "module_plot_BU.json",
        }
        try:
            names = set(os.listdir(current_path))
        except OSError:
            continue
        if names.intersection(marker_names):
            candidates.append((depth, current_path))
    candidates.sort(key=lambda item: (item[0], item[1]))
    # Do not truncate explicitly supplied roots: a later exact root must be
    # considered before provider generation. Discovery remains bounded by the
    # explicit depth and marker checks above.
    return [path for _depth, path in candidates]


def _find_source_module_monster_by_payload_name(
    source_module_dir: Any,
    canonical_slug: Any,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Find a source-module artifact whose payload names the requested monster.

    Some authored source modules use descriptive filenames rather than the
    canonical monster slug.  This fallback is deliberately limited to the
    explicitly supplied source module directory, sorted for deterministic
    results, and bounded so unrelated module trees are never searched.
    """
    try:
        root_path = os.fspath(source_module_dir) if source_module_dir else ""
    except TypeError:
        root_path = ""
    if not root_path:
        return None, []
    if isinstance(canonical_slug, Sequence) and not isinstance(
        canonical_slug, (str, bytes)
    ):
        accepted_slugs = {
            _canonical_monster_slug(value)
            for value in canonical_slug
            if isinstance(value, str) and value
        }
    else:
        accepted_slugs = {_canonical_monster_slug(canonical_slug)}
    monsters_dir = (
        root_path
        if os.path.basename(os.path.normpath(root_path)) == "monsters"
        else os.path.join(root_path, "monsters")
    )
    try:
        filenames = sorted(os.listdir(monsters_dir))
    except OSError:
        return None, []

    attempts: List[Dict[str, Any]] = []
    excluded = ("_BU.json", ".bak", ".backup", ".tmp", "_backup.json")
    for filename in filenames:
        if not filename.endswith(".json") or any(
            token in filename for token in excluded
        ):
            continue
        candidate_path = os.path.join(monsters_dir, filename)
        payload, reason, missing_fields = _load_monster_artifact(candidate_path)
        if reason != "schema_sufficient":
            attempts.append(
                {
                    "source": "module_scan",
                    "status": "rejected",
                    "path": _bounded_path(candidate_path),
                    "reason": reason,
                    "missing_required_fields": missing_fields,
                }
            )
            continue
        payload_name = payload.get("name") if isinstance(payload, Mapping) else ""
        if _canonical_monster_slug(payload_name) not in accepted_slugs:
            continue
        return candidate_path, attempts
    return None, attempts


def _write_staging_artifact(
    target_path: str,
    *,
    source_path: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
    """Copy or write one artifact, then leave verification to the caller."""
    if os.path.lexists(target_path) and os.path.islink(target_path):
        return False, "staging_target_symlink"
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if source_path:
            shutil.copy2(source_path, target_path)
        elif payload is not None:
            temporary_path = f"{target_path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as handle:
                json.dump(dict(payload), handle, indent=2, ensure_ascii=False)
            os.replace(temporary_path, target_path)
        else:
            return False, "missing_source"
    except (OSError, TypeError, ValueError):
        temporary_path = f"{target_path}.tmp"
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        return False, "staging_write_failed"
    return True, "reused"


def _default_monster_builder_path() -> str:
    """Return the repository monster builder used by opt-in generation."""
    return str(
        Path(__file__).resolve().parents[1]
        / "core"
        / "generators"
        / "monster_builder.py"
    )


def _generation_timeout(value: Any) -> float:
    """Return a bounded subprocess timeout for canonical generation."""
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = float(DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS)
    return max(1.0, min(timeout, 600.0))


def _generate_canonical_monster_in_staging(
    canonical_name: str,
    canonical_slug: str,
    staging_root: str,
    *,
    monster_builder_path: Optional[Union[str, Path]] = None,
    generation_timeout_seconds: Any = DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS,
    generation_context: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str, List[str]]:
    """Generate one already-canonical monster exclusively in staging.

    This is deliberately a narrow subprocess seam.  The caller has already
    performed semantic canonicalization; this helper never accepts raw prose,
    resolves aliases, or falls back to the live module tree.  The builder is
    given ``--output-directory`` rather than ``--module`` so its destination is
    the active staging root.
    """
    staging_path = os.path.abspath(os.fspath(staging_root))
    target_path = os.path.abspath(
        _monster_candidate_path(staging_path, canonical_slug)
    )
    staging_real = os.path.realpath(staging_path)
    target_real = os.path.realpath(target_path)
    try:
        Path(target_real).relative_to(Path(staging_real))
    except (OSError, ValueError):
        return False, "generation_target_outside_staging", []

    if os.path.lexists(target_path) and os.path.islink(target_path):
        return False, "generation_output_symlink", []

    builder = os.fspath(monster_builder_path) if monster_builder_path else _default_monster_builder_path()
    if not os.path.isfile(builder):
        return False, "generation_builder_missing", []

    def _remove_context_file() -> None:
        if context_path:
            try:
                os.remove(context_path)
            except OSError:
                pass

    context_path: Optional[str] = None
    if isinstance(generation_context, Mapping):
        context_path = os.path.join(staging_path, ".adaptation_monster_context.json")
        try:
            with open(context_path, "w", encoding="utf-8") as handle:
                json.dump(dict(generation_context), handle, indent=2, ensure_ascii=True)
        except (OSError, TypeError, ValueError):
            return False, "generation_context_write_failed", []

    command = [
        sys.executable,
        builder,
        canonical_name,
        "--output-directory",
        staging_path,
    ]
    if context_path:
        command.extend(["--context-file", context_path])
    # Keep the legacy CLI verbose outside adaptation, but make the adaptation
    # child explicitly suppress raw AI responses and payload-bearing errors.
    # Parent capture remains a second boundary and never forwards the streams.
    command.append("--adaptation-safe-output")
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_generation_timeout(generation_timeout_seconds),
        )
    except subprocess.TimeoutExpired:
        _remove_context_file()
        return False, "generation_timeout", []
    except (OSError, ValueError):
        _remove_context_file()
        return False, "generation_subprocess_error", []

    if getattr(completed, "returncode", 1) != 0:
        _remove_context_file()
        return False, "generation_nonzero_exit", []
    if not os.path.isfile(target_path):
        _remove_context_file()
        return False, "generation_missing_output", []
    if os.path.islink(target_path):
        _remove_context_file()
        return False, "generation_output_symlink", []
    try:
        Path(os.path.realpath(target_path)).relative_to(Path(staging_real))
    except (OSError, ValueError):
        _remove_context_file()
        return False, "generation_target_outside_staging", []

    _payload, verification_reason, missing_fields = _load_monster_artifact(
        target_path
    )
    if verification_reason == "invalid_json":
        try:
            os.remove(target_path)
        except OSError:
            pass
        _remove_context_file()
        return False, "generation_invalid_json", []
    if verification_reason != "schema_sufficient":
        try:
            os.remove(target_path)
        except OSError:
            pass
        _remove_context_file()
        return False, "generation_incomplete_schema", missing_fields
    if not _payload_matches_canonical_identity(_payload, canonical_name):
        try:
            os.remove(target_path)
        except OSError:
            pass
        _remove_context_file()
        return False, "generation_identity_mismatch", []
    if not isinstance(_payload, Mapping) or not isinstance(_payload.get("name"), str):
        try:
            os.remove(target_path)
        except OSError:
            pass
        _remove_context_file()
        return False, "generation_identity_missing", []
    _remove_context_file()
    return True, "generated", []


def materialize_adaptation_monsters(
    staging_root: Optional[Union[str, Path]],
    canonical_monster_refs: Any,
    encounter_seeds: Optional[Sequence[Any]] = None,
    *,
    source_module_dir: Optional[Union[str, Path]] = None,
    reusable_module_dirs: Optional[Sequence[Union[str, Path]]] = None,
    source_module_name: Optional[str] = None,
    compendium_path: Optional[Union[str, Path]] = None,
    compendium_lookup: Optional[Mapping[str, Any]] = None,
    allow_generation: bool = False,
    monster_builder_path: Optional[Union[str, Path]] = None,
    generation_timeout_seconds: Any = DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS,
    generation_context: Optional[Mapping[str, Any]] = None,
    approved_canonical_identities: Optional[Sequence[Any]] = None,
    canonical_registry: Any = None,
) -> Dict[str, Any]:
    """Materialize canonical monster artifacts into staging, reuse-first.

    Resolution is deliberately provider-free and ordered as staging, an
    explicit source module, reusable module roots, and finally the global or
    supplied compendium.  If ``allow_generation`` is explicitly true, only
    the already-canonical references supplied by the caller may reach the
    monster builder, and it receives ``staging_root`` through its explicit
    output-directory option.  Every successful artifact is verified at
    exactly ``staging_root/monsters/<canonical_slug>.json``.  No source module
    is ever written by this helper.
    """
    refs: List[str] = []
    seen_identity_variants: set[str] = set()
    if isinstance(canonical_monster_refs, Sequence) and not isinstance(
        canonical_monster_refs, (str, bytes)
    ):
        for raw_ref in list(canonical_monster_refs)[:MAX_ADAPTATION_ADVERSARIES]:
            ref = _safe_text(raw_ref, MAX_ADVERSARY_CHARS)
            identity = _adaptation_identity_variants(ref)
            variants = {
                value
                for value in identity.get("variants", [])
                if isinstance(value, str) and value
            }
            # Keep excluded scene labels individually diagnosable; identity
            # convergence applies to materializable monster identities only.
            duplicate_identity = (
                not _is_non_monster_scene_label(ref)
                and variants.intersection(seen_identity_variants)
            )
            if ref and variants and not duplicate_identity:
                refs.append(ref)
                if not _is_non_monster_scene_label(ref):
                    seen_identity_variants.update(variants)

    approved_slugs: Optional[set[str]] = None
    if approved_canonical_identities is not None:
        approved_slugs = set()
        if isinstance(approved_canonical_identities, Sequence) and not isinstance(
            approved_canonical_identities, (str, bytes)
        ):
            for value in list(approved_canonical_identities)[:MAX_ADAPTATION_ADVERSARIES]:
                identity = _adaptation_identity_variants(value)
                approved_slugs.update(_adaptation_identity_slugs(identity, value))
                canonical_key = _adaptation_canonical_identity_key(identity)
                if canonical_key:
                    approved_slugs.add(_canonical_monster_slug(canonical_key))

    result: Dict[str, Any] = {
        "status": "skipped",
        "monsters_planned": len(refs),
        "monsters_reused": 0,
        "monsters_generated": 0,
        "monsters_unresolved": 0,
        "monsters_excluded": 0,
        "encounters_planned": 0,
        "encounters_bound": 0,
        "encounters_scene_resolved": 0,
        "encounters_unresolved": 0,
        "encounters_unbound": 0,
        "unresolved_refs": [],
        "non_monster_refs": [],
        "artifact_paths": [],
        "resolution_log": [],
        "diagnostics": [],
    }
    if not refs:
        if encounter_seeds:
            result["encounters_planned"] = len(
                list(encounter_seeds)[:MAX_ADAPTATION_ENCOUNTERS]
            )
        return result

    if not staging_root:
        result["status"] = "degraded"
        result["monsters_unresolved"] = len(refs)
        result["unresolved_refs"] = refs
        result["diagnostics"] = [
            _diagnostic(
                "staging_root_missing",
                "adaptation materialization requires an explicit staging root",
            )
        ]
        return result

    try:
        staging_path = os.fspath(staging_root)
    except TypeError:
        staging_path = ""
    if not staging_path or os.path.lexists(staging_path) and os.path.islink(staging_path):
        result["status"] = "degraded"
        result["monsters_unresolved"] = len(refs)
        result["unresolved_refs"] = refs
        result["diagnostics"] = [
            _diagnostic(
                "invalid_staging_root",
                "staging root was invalid or a symlink; no artifact was written",
            )
        ]
        return result

    staging_monsters_dir = os.path.join(staging_path, "monsters")
    try:
        if os.path.lexists(staging_monsters_dir) and os.path.islink(
            staging_monsters_dir
        ):
            raise OSError("staging monsters directory is a symlink")
        os.makedirs(staging_monsters_dir, exist_ok=True)
    except OSError:
        result["status"] = "degraded"
        result["monsters_unresolved"] = len(refs)
        result["unresolved_refs"] = refs
        result["diagnostics"] = [
            _diagnostic(
                "staging_directory_unavailable",
                "staging monsters directory could not be prepared",
            )
        ]
        return result

    reusable_roots: List[Tuple[str, str]] = []
    if source_module_dir:
        for candidate in _normalize_reusable_root_candidates(source_module_dir):
            reusable_roots.append(("module", candidate))
    for root in list(reusable_module_dirs or []):
        try:
            root_path = os.fspath(root)
        except TypeError:
            continue
        if root_path:
            for candidate in _normalize_reusable_root_candidates(root_path):
                reusable_roots.append(("reusable", candidate))

    compendium: Dict[str, Any] = {}
    if isinstance(compendium_lookup, Mapping):
        for raw_key, payload in list(compendium_lookup.items())[:MAX_CANONICAL_MONSTER_VOCABULARY]:
            slug = _canonical_monster_slug(raw_key)
            if slug:
                compendium[slug] = payload
    elif compendium_path is not None:
        compendium = load_monster_compendium_lookup(os.fspath(compendium_path))
    else:
        compendium = load_monster_compendium_lookup()

    for ref in refs:
        registry_name, registry_status = _registry_canonical_reference(
            ref, canonical_registry
        )
        if isinstance(canonical_registry, Mapping) and registry_status != "matched":
            result["monsters_unresolved"] += 1
            result["unresolved_refs"].append(ref)
            result["resolution_log"].append(
                {
                    "ref": ref,
                    "canonical_slug": _canonical_monster_slug(ref),
                    "status": "unresolved",
                    "source": "registry",
                    "reason": "ambiguous_canonical_identity"
                    if registry_status == "ambiguous"
                    else "canonical_identity_not_approved",
                    "artifact_path": "",
                    "schema_sufficient": False,
                    "attempts": [],
                    "registry_resolution": registry_status,
                }
            )
            continue
        identity = _adaptation_identity_variants(registry_name or ref)
        resolution_ref = registry_name or ref
        raw_slug = _canonical_monster_slug(ref)
        canonical_key = _adaptation_canonical_identity_key(identity)
        canonical_name = (
            resolution_ref
            if canonical_key == identity.get("raw_key")
            else _adaptation_identity_display_name(canonical_key)
        )
        canonical_slug = _canonical_monster_slug(canonical_name)
        identity_lookup_slugs = [
            _canonical_monster_slug(value)
            for value in identity.get("variants", [])
            if isinstance(value, str) and value
        ]
        # Registry convergence owns the artifact identity.  Without an
        # explicit registry, retain the pre-existing exact-first compatibility
        # behavior and let the folded lookup phase converge aliases.
        target_slug = canonical_slug if registry_status == "matched" else raw_slug
        target_path = os.path.join(staging_monsters_dir, f"{target_slug}.json")
        attempts: List[Dict[str, Any]] = []
        resolved = False

        # Exact filename matches are never subject to the bounded diagnostic
        # attempt budget. Every supplied root gets a chance before payload
        # scans or provider generation begin.
        candidates: List[Tuple[str, str]] = [("staging", target_path)]
        for root_index, (source_label, root) in enumerate(reusable_roots):
            candidates.append(
                (source_label if root_index == 0 else f"{source_label}[{root_index}]",
                 _monster_candidate_path(root, target_slug))
            )
        if source_module_name and not source_module_dir:
            reusable_path = find_reusable_monster_path(
                str(source_module_name), resolution_ref
            )
            if reusable_path:
                candidates.append(("reusable", reusable_path))

        for source_label, candidate_path in candidates:
            if source_label == "staging" and os.path.islink(candidate_path):
                payload, reason, missing_fields = (
                    None,
                    "staging_target_symlink",
                    list(ADAPTATION_MONSTER_REQUIRED_FIELDS),
                )
            else:
                payload, reason, missing_fields = _load_monster_artifact(
                    candidate_path
                )
            if reason != "schema_sufficient":
                attempts.append(
                    {
                        "source": source_label,
                        "status": "rejected",
                        "path": _bounded_path(candidate_path),
                        "reason": reason,
                        "missing_required_fields": missing_fields,
                    }
                )
                continue

            if not _payload_matches_adaptation_identity(
                payload, identity, canonical_name
            ):
                attempts.append(
                    {
                        "source": source_label,
                        "status": "rejected",
                        "path": _bounded_path(candidate_path),
                        "reason": "artifact_identity_mismatch",
                    }
                )
                continue

            if source_label == "staging":
                resolved = True
            else:
                copied, copy_reason = _write_staging_artifact(
                    target_path,
                    source_path=candidate_path,
                )
                if not copied:
                    attempts.append(
                        {
                            "source": source_label,
                            "status": "rejected",
                            "path": _bounded_path(candidate_path),
                            "reason": copy_reason,
                        }
                    )
                    continue
                verified_payload, verify_reason, verify_missing = _load_monster_artifact(
                    target_path
                )
                resolved = (
                    verify_reason == "schema_sufficient"
                    and verified_payload is not None
                    and _payload_matches_adaptation_identity(
                        verified_payload, identity, canonical_name
                    )
                )
                if not resolved:
                    attempts.append(
                        {
                            "source": "staging",
                            "status": "rejected",
                            "path": _bounded_path(target_path),
                            "reason": verify_reason,
                            "missing_required_fields": verify_missing,
                        }
                    )
            if resolved:
                result["monsters_reused"] += 1
                result["artifact_paths"].append(_bounded_path(target_path))
                result["resolution_log"].append(
                    {
                        "ref": ref,
                        "canonical_slug": canonical_slug,
                        "status": "reused",
                        "source": source_label,
                        "reason": "reused",
                        "artifact_path": _bounded_path(target_path),
                        "source_path": _bounded_path(candidate_path)
                        if source_label != "staging"
                        else _bounded_path(target_path),
                        "schema_sufficient": True,
                        "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                        "registry_resolution": registry_status,
                    }
                )
                break

        # Folded lookup is intentionally a second phase.  Exact raw artifacts
        # above retain precedence, while all folded aliases converge on one
        # singular canonical staging target.
        if not resolved:
            folded_variants = [
                value
                for value in identity.get("variants", [])[1:]
                if isinstance(value, str) and value
            ]
            target_path = os.path.join(
                staging_monsters_dir, f"{canonical_slug}.json"
            )
            folded_candidates: List[Tuple[str, str]] = [
                ("staging_folded", target_path)
            ]
            for variant_index, variant in enumerate(folded_variants):
                variant_slug = _canonical_monster_slug(variant)
                for root_index, (source_label, root) in enumerate(reusable_roots):
                    label = source_label if root_index == 0 else f"{source_label}[{root_index}]"
                    folded_candidates.append(
                        (
                            f"{label}_folded[{variant_index}]",
                            _monster_candidate_path(root, variant_slug),
                        )
                    )
            for source_label, candidate_path in folded_candidates:
                if source_label == "staging_folded" and os.path.islink(candidate_path):
                    payload, reason, missing_fields = (
                        None,
                        "staging_target_symlink",
                        list(ADAPTATION_MONSTER_REQUIRED_FIELDS),
                    )
                else:
                    payload, reason, missing_fields = _load_monster_artifact(
                        candidate_path
                    )
                if reason != "schema_sufficient":
                    attempts.append(
                        {
                            "source": source_label,
                            "status": "rejected",
                            "path": _bounded_path(candidate_path),
                            "reason": reason,
                            "missing_required_fields": missing_fields,
                        }
                    )
                    continue
                if not _payload_matches_adaptation_identity(
                    payload, identity, canonical_name
                ):
                    attempts.append(
                        {
                            "source": source_label,
                            "status": "rejected",
                            "path": _bounded_path(candidate_path),
                            "reason": "artifact_identity_mismatch",
                        }
                    )
                    continue
                if source_label == "staging_folded":
                    resolved = True
                else:
                    copied, copy_reason = _write_staging_artifact(
                        target_path, source_path=candidate_path
                    )
                    if not copied:
                        attempts.append(
                            {
                                "source": source_label,
                                "status": "rejected",
                                "path": _bounded_path(candidate_path),
                                "reason": copy_reason,
                            }
                        )
                        continue
                    verified_payload, verify_reason, verify_missing = _load_monster_artifact(
                        target_path
                    )
                    resolved = (
                        verify_reason == "schema_sufficient"
                        and verified_payload is not None
                        and _payload_matches_adaptation_identity(
                            verified_payload, identity, canonical_name
                        )
                    )
                    if not resolved:
                        attempts.append(
                            {
                                "source": "staging_folded",
                                "status": "rejected",
                                "path": _bounded_path(target_path),
                                "reason": verify_reason,
                                "missing_required_fields": verify_missing,
                            }
                        )
                if resolved:
                    result["monsters_reused"] += 1
                    result["artifact_paths"].append(_bounded_path(target_path))
                    result["resolution_log"].append(
                        {
                    "ref": ref,
                            "canonical_slug": canonical_slug,
                            "status": "reused",
                            "source": source_label,
                            "reason": "reused_folded_identity",
                            "artifact_path": _bounded_path(target_path),
                            "source_path": _bounded_path(candidate_path),
                            "schema_sufficient": True,
                            "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                        }
                    )
                    break

        # Some authored source modules use descriptive filenames (for
        # example, "2_darkmantles_hiding_among_the_broken_stones.json")
        # while the payload carries the canonical identity.  Only inspect the
        # explicitly supplied source module after exact filename resolution;
        # do not broaden this fallback to unrelated module directories.
        if not resolved and source_module_dir:
            descriptive_path, scan_attempts = (
                _find_source_module_monster_by_payload_name(
                    source_module_dir,
                    identity_lookup_slugs,
                )
            )
            attempts.extend(scan_attempts[:MAX_MATERIALIZATION_ATTEMPTS])
            if descriptive_path:
                copied, copy_reason = _write_staging_artifact(
                    target_path,
                    source_path=descriptive_path,
                )
                if copied:
                    verified_payload, verify_reason, verify_missing = (
                        _load_monster_artifact(target_path)
                    )
                    resolved = (
                        verify_reason == "schema_sufficient"
                        and verified_payload is not None
                        and _payload_matches_adaptation_identity(
                            verified_payload, identity, canonical_name
                        )
                    )
                    if not resolved:
                        attempts.append(
                            {
                                "source": "staging",
                                "status": "rejected",
                                "path": _bounded_path(target_path),
                                "reason": verify_reason,
                                "missing_required_fields": verify_missing,
                            }
                        )
                else:
                    attempts.append(
                        {
                            "source": "module_scan",
                            "status": "rejected",
                            "path": _bounded_path(descriptive_path),
                            "reason": copy_reason,
                        }
                    )
                if resolved:
                    result["monsters_reused"] += 1
                    result["artifact_paths"].append(_bounded_path(target_path))
                    result["resolution_log"].append(
                        {
                            "ref": ref,
                            "canonical_slug": canonical_slug,
                            "status": "reused",
                            "source": "module_scan",
                            "reason": "reused_payload_name_match",
                            "artifact_path": _bounded_path(target_path),
                            "source_path": _bounded_path(descriptive_path),
                            "schema_sufficient": True,
                            "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                        }
                    )

        # Descriptive filenames are valid in every explicitly supplied root,
        # not only the source module. Exact matches above always win.
        if not resolved:
            for root_index, (_source_label, root) in enumerate(reusable_roots):
                descriptive_path, scan_attempts = _find_source_module_monster_by_payload_name(
                    root, identity_lookup_slugs
                )
                attempts.extend(scan_attempts[:MAX_MATERIALIZATION_ATTEMPTS])
                if not descriptive_path:
                    continue
                copied, copy_reason = _write_staging_artifact(
                    target_path, source_path=descriptive_path
                )
                if copied:
                    _verified, verify_reason, verify_missing = _load_monster_artifact(target_path)
                    resolved = (
                        verify_reason == "schema_sufficient"
                        and _verified is not None
                        and _payload_matches_adaptation_identity(
                            _verified, identity, canonical_name
                        )
                    )
                else:
                    verify_reason, verify_missing = copy_reason, []
                if resolved:
                    result["monsters_reused"] += 1
                    result["artifact_paths"].append(_bounded_path(target_path))
                    result["resolution_log"].append({
                        "ref": ref, "canonical_slug": canonical_slug,
                        "status": "reused", "source": f"module_scan[{root_index}]",
                        "reason": "reused_payload_name_match",
                        "artifact_path": _bounded_path(target_path),
                        "source_path": _bounded_path(descriptive_path),
                        "schema_sufficient": True,
                        "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                    })
                    break

        if not resolved:
            compendium_payload = compendium.get(canonical_slug)
            if isinstance(compendium_payload, Mapping):
                missing_fields = [
                    field
                    for field in ADAPTATION_MONSTER_REQUIRED_FIELDS
                    if compendium_payload.get(field) in (None, "")
                ]
                if not missing_fields:
                    written, write_reason = _write_staging_artifact(
                        target_path,
                        payload=compendium_payload,
                    )
                    if written:
                        verified_payload, verify_reason, verify_missing = _load_monster_artifact(
                            target_path
                        )
                        resolved = (
                            verify_reason == "schema_sufficient"
                            and verified_payload is not None
                            and _payload_matches_adaptation_identity(
                                verified_payload, identity, canonical_name
                            )
                        )
                        if not resolved:
                            write_reason = verify_reason
                            missing_fields = verify_missing
                    attempts.append(
                        {
                            "source": "compendium",
                            "status": "reused" if resolved else "rejected",
                            "path": _bounded_path(target_path),
                            "reason": "reused" if resolved else write_reason,
                            "missing_required_fields": missing_fields,
                        }
                    )
                else:
                    attempts.append(
                        {
                            "source": "compendium",
                            "status": "rejected",
                            "path": _bounded_path(target_path),
                            "reason": "missing_required_fields",
                            "missing_required_fields": missing_fields,
                        }
                )

            if resolved:
                result["monsters_reused"] += 1
                result["artifact_paths"].append(_bounded_path(target_path))
                result["resolution_log"].append(
                    {
                        "ref": ref,
                        "canonical_slug": canonical_slug,
                        "status": "reused",
                        "source": "compendium",
                        "reason": "reused",
                        "artifact_path": _bounded_path(target_path),
                        "source_path": _bounded_path(compendium_path or "compendium"),
                        "schema_sufficient": True,
                        "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                    }
                )
            else:
                # Exclusion is deliberately after every exact/descriptive
                # reusable-root and compendium lookup. A schema-sufficient
                # artifact always wins, even when its name contains a known
                # scene-label phrase.
                if _is_non_monster_scene_label(ref):
                    result["monsters_excluded"] += 1
                    result["non_monster_refs"].append(ref)
                    result["resolution_log"].append(
                        {
                            "ref": ref,
                            "canonical_slug": canonical_slug,
                            "status": "excluded",
                            "source": "none",
                            "reason": "non_monster_scene_entity",
                            "artifact_path": _bounded_path(target_path),
                            "schema_sufficient": False,
                            "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                        }
                    )
                    if len(result["diagnostics"]) < MAX_DIAGNOSTICS:
                        result["diagnostics"].append(
                            _diagnostic(
                                "non_monster_scene_entity",
                                "scene or hazard label was excluded from monster materialization",
                                adversary=ref,
                            )
                        )
                    continue
                generation_approved = (
                    approved_slugs is None or canonical_slug in approved_slugs
                )
                if allow_generation and generation_approved:
                    generated, generation_reason, generation_missing_fields = (
                        _generate_canonical_monster_in_staging(
                            canonical_name,
                            canonical_slug,
                            staging_path,
                            monster_builder_path=monster_builder_path,
                            generation_timeout_seconds=generation_timeout_seconds,
                            generation_context=generation_context,
                        )
                    )
                    attempts.append(
                        {
                            "source": "generated",
                            "status": "generated" if generated else "rejected",
                            "path": _bounded_path(target_path),
                            "reason": generation_reason,
                            "missing_required_fields": generation_missing_fields,
                        }
                    )
                    if len(result["diagnostics"]) < MAX_DIAGNOSTICS:
                        diagnostic_message = (
                            "canonical monster was generated and schema-verified in staging"
                            if generated
                            else "canonical monster generation did not produce a schema-sufficient staging artifact"
                        )
                        result["diagnostics"].append(
                            _diagnostic(
                                generation_reason,
                                diagnostic_message,
                                adversary=ref,
                            )
                        )
                    if generated:
                        result["monsters_generated"] += 1
                        result["artifact_paths"].append(_bounded_path(target_path))
                        result["resolution_log"].append(
                            {
                                "ref": ref,
                                "canonical_slug": canonical_slug,
                                # The binding helper treats schema-verified
                                # artifacts as resolved when status is reused;
                                # source still records that this one was
                                # generated in staging.
                                "status": "reused",
                                "source": "generated",
                                "reason": "generated",
                                "artifact_path": _bounded_path(target_path),
                                "schema_sufficient": True,
                                "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                            }
                        )
                        continue
                elif allow_generation and not generation_approved:
                    attempts.append(
                        {
                            "source": "generated",
                            "status": "rejected",
                            "path": _bounded_path(target_path),
                            "reason": "identity_not_approved",
                            "missing_required_fields": [],
                        }
                    )

                final_reason = "file_not_found"
                missing_fields: List[str] = []
                for attempt in reversed(attempts):
                    if attempt.get("reason") not in {"file_not_found", "missing_path"}:
                        final_reason = str(attempt.get("reason"))
                        missing_fields = list(attempt.get("missing_required_fields") or [])
                        break
                result["monsters_unresolved"] += 1
                result["unresolved_refs"].append(ref)
                result["resolution_log"].append(
                    {
                        "ref": ref,
                        "canonical_slug": canonical_slug,
                        "status": "unresolved",
                        "source": "none",
                        "reason": final_reason,
                        "artifact_path": _bounded_path(target_path),
                        "schema_sufficient": False,
                        "missing_required_fields": missing_fields,
                        "attempts": attempts[:MAX_MATERIALIZATION_ATTEMPTS],
                    }
                )

    result["status"] = "pass" if not result["unresolved_refs"] else "degraded"
    seeds = list(encounter_seeds or [])[:MAX_ADAPTATION_ENCOUNTERS]
    result["encounters_planned"] = len(seeds)
    binding = _bind_adaptation_encounters(seeds, result["resolution_log"])
    result["encounters_bound"] = int(binding.get("seeds_bound", 0))
    result["encounters_unresolved"] = int(binding.get("seeds_unresolved", 0))
    result["encounters_unbound"] = int(binding.get("seeds_unbound", 0))
    result["encounters_scene_resolved"] = int(
        binding.get("seeds_scene_resolved", 0)
    )
    result["encounter_bindings"] = list(binding.get("bindings", []))[
        :MAX_ADAPTATION_ENCOUNTERS
    ]
    if binding.get("status") == "degraded":
        result["status"] = "degraded"
    return result


def materialize_adaptation_monster_artifacts(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Descriptive alias for the staging-aware adaptation materializer."""
    return materialize_adaptation_monsters(*args, **kwargs)


_QUANTITY_PREFIX_RE = re.compile(
    r"^(?:(?:\d+|one|a|an|two|three|four|five|six|seven|eight|nine|ten)"
    r"(?![a-z0-9])"
    r"\s*(?:x\s*)?|(?:a\s+)?(?:pair|couple|group|trio)\s+of\s+)"
)
_NON_MONSTER_RE = re.compile(
    r"\b(?:npc|ally|allies|allied|worker|workers|villager|villagers|"
    r"bystander|bystanders|civilian|civilians|patron|patrons|merchant|"
    r"merchants|scene|crowd|crowds|staff|servant|servants)\b",
    re.IGNORECASE,
)
# These are deliberately narrow scene/hazard labels observed in adaptation
# dossiers.  Do not broaden this into a generic keyword classifier: names such
# as "guardian" and "ooze" can be legitimate canonical creatures.
_NON_MONSTER_SCENE_LABEL_RE = re.compile(
    r"\b(?:false\s+villagers?|glyph\s+ward|cave\s+hazards?)\b",
    re.IGNORECASE,
)
_QUANTITY_WORDS = {
    "one": 1,
    "a": 1,
    "an": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _monster_tokens(value: Any) -> List[str]:
    """Return deterministic lowercase tokens for phrase matching."""
    return re.findall(r"[a-z0-9]+", _safe_text(value, MAX_MONSTER_ENTRY_CHARS).lower())


def _is_non_monster_scene_label(value: Any) -> bool:
    """Return whether a bounded dossier label is clearly scene-only.

    This is an adaptation-only safety valve for known scene/hazard labels. It
    intentionally uses word boundaries and does not infer from broad words
    such as ``guardian`` or ``ooze``.
    """
    text = _safe_text(value, MAX_MONSTER_ENTRY_CHARS)
    return bool(text and (_NON_MONSTER_RE.search(text) or _NON_MONSTER_SCENE_LABEL_RE.search(text)))


def _bind_adaptation_encounters(
    seeds: Sequence[Mapping[str, Any]],
    resolution_log: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Bind adaptation seeds while treating excluded scene labels as resolved.

    The shared accurate-ingest binder correctly treats an absent resolution as
    unbound. Adaptation dossiers additionally contain explicitly excluded
    scene/hazard adversaries, which need a truthful ``scene_resolved`` outcome
    without weakening unresolved canonical monster failures.
    """
    log = [entry for entry in resolution_log if isinstance(entry, Mapping)]
    bindings: List[Dict[str, Any]] = []
    for seed in list(seeds)[:MAX_ADAPTATION_ENCOUNTERS]:
        raw_adversaries = seed.get("adversaries", [])
        adversaries = [value for value in raw_adversaries if isinstance(value, str)] if isinstance(raw_adversaries, Sequence) and not isinstance(raw_adversaries, (str, bytes)) else []
        resolved: List[Mapping[str, Any]] = []
        unresolved: List[Mapping[str, Any]] = []
        excluded: List[Mapping[str, Any]] = []
        excluded_adversary_indexes: set[int] = set()
        for entry in log:
            entry_labels = [entry.get("ref", ""), entry.get("canonical_slug", "")]
            matching_indexes = {
                index
                for index, adversary in enumerate(adversaries)
                if any(
                    _adaptation_identity_matches(entry_label, adversary)
                    for entry_label in entry_labels
                    if isinstance(entry_label, str) and entry_label
                )
            }
            matches_seed = bool(matching_indexes)
            if not matches_seed:
                continue
            if entry.get("status") == "reused":
                resolved.append(entry)
            elif entry.get("status") == "unresolved":
                unresolved.append(entry)
            elif entry.get("status") == "excluded":
                excluded.append(entry)
                excluded_adversary_indexes.update(matching_indexes)
        if unresolved:
            bindings.append({"seed": seed, "status": "unresolved", "monster_ref": None, "artifact_path": None, "unresolved_refs": [entry.get("ref") for entry in unresolved], "reason": "unresolved_ref"})
        elif resolved:
            entry = resolved[0]
            bindings.append({"seed": seed, "status": "bound", "monster_ref": entry.get("ref"), "artifact_path": entry.get("artifact_path"), "unresolved_refs": [], "reason": "bound"})
        elif adversaries and len(excluded_adversary_indexes) == len(adversaries):
            bindings.append({"seed": seed, "status": "scene_resolved", "monster_ref": None, "artifact_path": None, "unresolved_refs": [], "reason": "non_monster_scene_entity"})
        else:
            bindings.append({"seed": seed, "status": "unbound", "monster_ref": None, "artifact_path": None, "unresolved_refs": [], "reason": "no_source_ref"})
    bound = sum(1 for item in bindings if item["status"] == "bound")
    scene_resolved = sum(
        1 for item in bindings if item["status"] == "scene_resolved"
    )
    unresolved_count = sum(1 for item in bindings if item["status"] == "unresolved")
    unbound = sum(1 for item in bindings if item["status"] == "unbound")
    return {
        "status": "degraded" if unresolved_count else "pass",
        "seeds_planned": len(bindings),
        "seeds_bound": bound,
        "seeds_scene_resolved": scene_resolved,
        "seeds_unresolved": unresolved_count,
        "seeds_unbound": unbound,
        "bindings": bindings,
    }


def _singular_plural_forms(tokens: List[str]) -> List[str]:
    """Return bounded token forms for ordinary creature singular/plural text."""
    if not tokens:
        return []
    forms = [tokens]
    last = tokens[-1]
    if last.endswith("ies") and len(last) > 3:
        forms.append(tokens[:-1] + [last[:-3] + "y"])
    elif last.endswith("es") and len(last) > 3:
        forms.append(tokens[:-1] + [last[:-2]])
    elif last.endswith("s") and len(last) > 1:
        forms.append(tokens[:-1] + [last[:-1]])
    else:
        forms.append(tokens[:-1] + [last + "s"])
    return forms


def _canonical_vocabulary_entries(
    canonical_vocabulary: Any,
) -> List[Tuple[str, List[str]]]:
    """Normalize a bounded canonical vocabulary into canonical name/alias pairs.

    Supported inputs are strings, ``{"name": ..., "aliases": [...]}`` objects,
    and mappings from canonical names to alias lists.  Invalid entries are
    ignored rather than converted into invented monster identities.
    """
    if isinstance(canonical_vocabulary, Mapping):
        raw_entries: List[Any] = []
        for key, value in list(canonical_vocabulary.items())[
            :MAX_CANONICAL_MONSTER_VOCABULARY
        ]:
            if isinstance(value, Mapping):
                item = dict(value)
                item.setdefault("name", key)
                raw_entries.append(item)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                raw_entries.append({"name": key, "aliases": list(value)})
            else:
                raw_entries.append(key)
    elif isinstance(canonical_vocabulary, Sequence) and not isinstance(
        canonical_vocabulary, (str, bytes)
    ):
        raw_entries = list(canonical_vocabulary)[:MAX_CANONICAL_MONSTER_VOCABULARY]
    else:
        raw_entries = []

    result: List[Tuple[str, List[str]]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        aliases: List[Any] = []
        if isinstance(raw_entry, Mapping):
            name = raw_entry.get("name", raw_entry.get("canonical_name"))
            raw_aliases = raw_entry.get("aliases", [])
            if isinstance(raw_aliases, Sequence) and not isinstance(
                raw_aliases, (str, bytes)
            ):
                aliases.extend(list(raw_aliases)[:8])
        else:
            name = raw_entry
        canonical_name = _safe_text(name, MAX_MONSTER_ENTRY_CHARS)
        canonical_tokens = _monster_tokens(canonical_name)
        if not canonical_tokens:
            continue
        identity_key = " ".join(canonical_tokens)
        if identity_key in seen:
            continue
        seen.add(identity_key)
        variants: List[str] = [identity_key]
        for form in _singular_plural_forms(canonical_tokens):
            variant = " ".join(form)
            if variant not in variants:
                variants.append(variant)
        for alias in aliases:
            alias_tokens = _monster_tokens(alias)
            if not alias_tokens:
                continue
            for form in _singular_plural_forms(alias_tokens):
                variant = " ".join(form)
                if variant not in variants:
                    variants.append(variant)
        result.append((canonical_name, variants[:12]))
    return result


def _registry_vocabulary_entries(
    canonical_registry: Any,
) -> List[Tuple[str, List[str]]]:
    """Build normalization vocabulary from the adaptation registry only.

    The registry is the identity authority for adaptation normalization.  This
    adapter deliberately exposes only its approved canonical names and bounded
    aliases; it does not infer identities from artifact filenames or prose.
    """
    if not isinstance(canonical_registry, Mapping):
        return []
    entries = canonical_registry.get("entries")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return []
    vocabulary: List[Tuple[str, List[str]]] = []
    for entry in list(entries)[:MAX_IDENTITY_REGISTRY_ENTRIES]:
        if not isinstance(entry, Mapping) or entry.get("approved") is not True:
            continue
        canonical_name = _safe_text(
            entry.get("canonical_identity", ""), MAX_MONSTER_ENTRY_CHARS
        )
        if not canonical_name:
            continue
        aliases = entry.get("aliases", [])
        values: List[Any] = [canonical_name]
        if isinstance(aliases, Sequence) and not isinstance(aliases, (str, bytes)):
            values.extend(list(aliases)[:MAX_IDENTITY_REGISTRY_ALIASES])
        variants: List[str] = []
        for value in values:
            text = _safe_text(value, MAX_MONSTER_ENTRY_CHARS)
            tokens = _monster_tokens(text)
            if not tokens:
                continue
            for form in _singular_plural_forms(tokens):
                variant = " ".join(form)
                if variant not in variants:
                    variants.append(variant)
        vocabulary.append((canonical_name, variants[:12]))
    return vocabulary


def _registry_canonical_reference(
    reference: Any,
    canonical_registry: Any,
) -> Tuple[Optional[str], str]:
    """Resolve one raw reference against approved registry identities."""
    vocabulary = _registry_vocabulary_entries(canonical_registry)
    if not vocabulary:
        return None, "registry_unavailable"
    canonical_name, _indexes, status = _find_canonical_match(
        _safe_text(reference, MAX_MONSTER_ENTRY_CHARS), vocabulary
    )
    return canonical_name, status


def _strip_quantity_prefix(text: str) -> Tuple[str, str, Optional[int]]:
    """Strip only a leading quantity phrase and return its bounded hint."""
    match = _QUANTITY_PREFIX_RE.match(text)
    if not match:
        return text, "", None
    quantity_text = _safe_text(match.group(0), MAX_QUANTITY_CHARS)
    quantity_key = quantity_text.lower().strip()
    numeric_match = re.search(r"\d+", quantity_key)
    quantity_value: Optional[int] = None
    if numeric_match:
        quantity_value = min(int(numeric_match.group(0)), 999)
    else:
        for word, value in _QUANTITY_WORDS.items():
            if re.search(rf"\b{word}\b", quantity_key):
                quantity_value = value
                break
    remainder = text[match.end() :].lstrip(" -:;,\t")
    return remainder, quantity_text, quantity_value


def _entry_payload(entry: Any) -> Tuple[str, str, Optional[Dict[str, int]]]:
    """Extract bounded identity text, description, and quantity metadata."""
    if isinstance(entry, str):
        return _safe_text(entry, MAX_MONSTER_ENTRY_CHARS), "", None
    if not isinstance(entry, Mapping):
        return "", "", None
    raw_name = entry.get("name", entry.get("monster", entry.get("creature", "")))
    name = _safe_text(raw_name, MAX_MONSTER_ENTRY_CHARS)
    description = _safe_text(entry.get("description", ""), MAX_MONSTER_PROSE_CHARS)
    raw_quantity = entry.get("quantity")
    quantity: Optional[Dict[str, int]] = None
    if isinstance(raw_quantity, Mapping):
        minimum = raw_quantity.get("min")
        maximum = raw_quantity.get("max")
        if (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
        ):
            quantity = {
                "min": max(0, min(minimum, 999)),
                "max": max(1, min(maximum, 999)),
            }
            if quantity["max"] < quantity["min"]:
                quantity["max"] = quantity["min"]
    return name, description, quantity


def _find_canonical_match(
    text: str,
    vocabulary: List[Tuple[str, List[str]]],
) -> Tuple[Optional[str], List[int], str]:
    """Find one longest, unambiguous canonical phrase in bounded input text.

    Quantity tokens may occur inside an authored phrase, rather than only at
    its beginning.  When present, they scope matching to creature phrases
    after the quantity (for example, ``Vask's 2 grimlock attendants``).  This
    prevents an owner name from competing with the actual creature identity.
    Without a quantity cue, a possessive prefix is not sufficient evidence to
    map a named custom adversary to its owner's canonical name.
    """
    tokens = _monster_tokens(text)
    candidates: List[Tuple[int, int, str]] = []
    for canonical_name, variants in vocabulary:
        for variant in variants:
            variant_tokens = variant.split()
            width = len(variant_tokens)
            if not width or width > len(tokens):
                continue
            for start in range(len(tokens) - width + 1):
                if tokens[start : start + width] == variant_tokens:
                    candidates.append((width, start, canonical_name))

    quantity_indexes = _quantity_token_indexes(tokens)
    if quantity_indexes:
        quantity_candidates = [
            candidate
            for candidate in candidates
            if any(quantity_index < candidate[1] for quantity_index in quantity_indexes)
        ]
        if quantity_candidates:
            candidates = quantity_candidates
    else:
        # A possessive owner followed by a role/title is a named scene or
        # custom adversary, not evidence that the owner itself is the monster.
        # An exact canonical phrase remains valid, as does an explicitly
        # canonical custom phrase supplied by the adaptation dossier.
        filtered_candidates: List[Tuple[int, int, str]] = []
        for candidate in candidates:
            width, start, _canonical_name = candidate
            end = start + width
            is_exact = start == 0 and end == len(tokens)
            has_possessive_owner = start > 0 and tokens[start - 1] == "s"
            has_possessive_suffix = end < len(tokens) and tokens[end] == "s"
            if not is_exact and (has_possessive_owner or has_possessive_suffix):
                continue
            filtered_candidates.append(candidate)
        candidates = filtered_candidates
    if not candidates:
        return None, [], "unresolved"
    longest = max(candidate[0] for candidate in candidates)
    selected = [candidate for candidate in candidates if candidate[0] == longest]
    canonical_names = sorted({candidate[2] for candidate in selected})
    if len(canonical_names) != 1:
        return None, [], "ambiguous"
    start = selected[0][1]
    return canonical_names[0], list(range(start, start + longest)), "matched"


def _quantity_token_indexes(tokens: Sequence[str]) -> List[int]:
    """Return bounded indexes for quantity tokens embedded in a phrase."""
    indexes: List[int] = []
    for index, token in enumerate(tokens):
        if token.isdigit() or token in _QUANTITY_WORDS:
            indexes.append(index)
    return indexes[:4]


def _remaining_prose(text: str, matched_indexes: List[int]) -> str:
    """Preserve non-identity words as bounded authored descriptive prose."""
    tokens = _monster_tokens(text)
    matched = set(matched_indexes)
    prose = " ".join(token for index, token in enumerate(tokens) if index not in matched)
    return _safe_text(prose, MAX_MONSTER_PROSE_CHARS)


def _normalization_record(
    original_text: str,
    description: str,
    source_location: str,
    classification: str,
    reason: str,
) -> Dict[str, Any]:
    """Build a bounded excluded/unresolved entry record."""
    record: Dict[str, Any] = {
        "original_text": _safe_text(original_text, MAX_MONSTER_ENTRY_CHARS),
        "classification": _safe_text(classification, 48),
        "reason": _safe_text(reason, 96),
    }
    if description:
        record["description"] = _safe_text(description, MAX_MONSTER_PROSE_CHARS)
    if source_location:
        record["source_location"] = _safe_text(source_location, MAX_SEED_TEXT_CHARS)
    return record


def normalize_adaptation_location_monsters(
    location_monsters: Any,
    canonical_vocabulary: Any,
    *,
    canonical_registry: Any = None,
    source_location: str = "",
    known_npcs: Optional[Sequence[str]] = None,
    known_allies: Optional[Sequence[str]] = None,
    approved_artifact_names: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Normalize adaptation ``location.monsters`` entries without providers.

    The return value contains canonical structural monster records and bounded
    excluded/unresolved records.  A canonical identity is emitted only when
    exactly one longest vocabulary phrase matches.  Quantity prefixes and
    descriptive words are removed from the structural identity, while the
    original text and remaining prose are retained for later authored fields.
    """
    # Adaptation callers must prefer the task-1.1 registry.  The vocabulary
    # argument remains as a compatibility fallback for existing provider-free
    # guardrail tests and legacy callers of this adaptation helper.
    vocabulary = _registry_vocabulary_entries(canonical_registry)
    if not vocabulary:
        vocabulary = _canonical_vocabulary_entries(canonical_vocabulary)
    npc_keys = {_adversary_key(_safe_text(value, MAX_MONSTER_ENTRY_CHARS)) for value in (known_npcs or [])}
    ally_keys = {_adversary_key(_safe_text(value, MAX_MONSTER_ENTRY_CHARS)) for value in (known_allies or [])}
    artifact_keys = {
        _adversary_key(_safe_text(value, MAX_MONSTER_ENTRY_CHARS))
        for value in (approved_artifact_names or [])
    }
    if not isinstance(location_monsters, Sequence) or isinstance(
        location_monsters, (str, bytes)
    ):
        entries: List[Any] = []
        diagnostics = [
            _diagnostic(
                "invalid_location_monsters",
                "location monsters value was not a list; no structural identities were emitted",
            )
        ]
    else:
        entries = list(location_monsters)[:MAX_LOCATION_MONSTER_ENTRIES]
        diagnostics = []
        if len(location_monsters) > MAX_LOCATION_MONSTER_ENTRIES:
            diagnostics.append(
                _diagnostic(
                    "location_monster_bound_reached",
                    "additional location monster entries were ignored after the bound",
                )
            )

    normalized: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    contradiction_diagnostics: List[Dict[str, Any]] = []
    for entry in entries:
        name, description, quantity = _entry_payload(entry)
        original_text = name or description
        if not original_text:
            if len(excluded) < MAX_EXCLUDED_MONSTER_RECORDS:
                excluded.append(
                    _normalization_record(
                        "", description, source_location, "invalid_entry", "missing_name"
                    )
                )
            continue
        _match_text, quantity_text, quantity_value = _strip_quantity_prefix(original_text)
        if quantity_value is None:
            original_tokens = _monster_tokens(original_text)
            for quantity_index in _quantity_token_indexes(original_tokens):
                quantity_token = original_tokens[quantity_index]
                if quantity_token.isdigit():
                    quantity_value = min(int(quantity_token), 999)
                else:
                    quantity_value = _QUANTITY_WORDS.get(quantity_token)
                if quantity_value is not None:
                    quantity_text = quantity_token
                    break
        canonical_name, matched_indexes, match_status = _find_canonical_match(
            original_text, vocabulary
        )
        entry_key = _adversary_key(original_text)
        if entry_key in ally_keys or re.search(r"\b(?:ally|allied)\b", original_text, re.I):
            if len(excluded) < MAX_EXCLUDED_MONSTER_RECORDS:
                excluded.append(
                    _normalization_record(
                        original_text,
                        description,
                        source_location,
                        "ally",
                        "non_monster_ally",
                    )
                )
            continue
        if (
            (entry_key in npc_keys or _NON_MONSTER_RE.search(original_text))
            and not (
                canonical_name
                and _adversary_key(canonical_name) in artifact_keys
            )
        ):
            classification = "npc" if entry_key in npc_keys or re.search(r"\bnpc\b", original_text, re.I) else "scene_prose"
            if len(excluded) < MAX_EXCLUDED_MONSTER_RECORDS:
                excluded.append(
                    _normalization_record(
                        original_text,
                        description,
                        source_location,
                        classification,
                        "non_monster_scene_entity",
                    )
                )
            continue
        if match_status != "matched" or canonical_name is None:
            classification = "ambiguous" if match_status == "ambiguous" else "unresolved_prose"
            record = _normalization_record(
                original_text,
                description,
                source_location,
                classification,
                "ambiguous_canonical_match" if classification == "ambiguous" else "no_canonical_match",
            )
            if len(unresolved) < MAX_EXCLUDED_MONSTER_RECORDS:
                unresolved.append(record)
            continue

        prose = _remaining_prose(
            original_text,
            matched_indexes + _quantity_token_indexes(_monster_tokens(original_text)),
        )
        if description:
            prose = _safe_text("; ".join(part for part in (prose, description) if part), MAX_MONSTER_PROSE_CHARS)
        normalized_record: Dict[str, Any] = {
            "name": canonical_name,
            "canonical_name": canonical_name,
            "original_text": _safe_text(original_text, MAX_MONSTER_ENTRY_CHARS),
            "descriptive_prose": prose,
        }
        if source_location:
            normalized_record["source_location"] = _safe_text(source_location, MAX_SEED_TEXT_CHARS)
        if quantity is not None:
            normalized_record["quantity"] = quantity
        elif quantity_value is not None:
            normalized_record["quantity_hint"] = quantity_text
            normalized_record["quantity"] = {"min": quantity_value, "max": quantity_value}
        effective_quantity = normalized_record.get("quantity")
        # Keep structured quantity authoritative, but expose bounded scene
        # evidence when prose describes multiple manifestations.  This is a
        # content diagnostic for the later LLM workflow, never a rewrite.
        if (
            isinstance(effective_quantity, Mapping)
            and effective_quantity.get("min") == 1
            and effective_quantity.get("max") == 1
            and re.search(r"\b(?:two|2|multiple|pair|both)\b", prose, re.I)
        ):
            contradiction_diagnostics.append(
                {
                    "code": "quantity_prose_contradiction",
                    "message": "structured quantity is one while bounded scene prose describes multiple manifestations",
                    "canonical_name": _safe_text(canonical_name, MAX_MONSTER_ENTRY_CHARS),
                    "quantity": {"min": 1, "max": 1},
                    "source_location": _safe_text(source_location, MAX_SEED_TEXT_CHARS),
                    "scene_evidence": _safe_text(prose, MAX_MONSTER_PROSE_CHARS),
                }
            )
        normalized.append(normalized_record)
        if len(normalized) >= MAX_NORMALIZED_MONSTER_RECORDS:
            diagnostics.append(
                _diagnostic(
                    "normalized_monster_bound_reached",
                    "additional canonical monster identities were ignored after the bound",
                )
            )
            break

    if unresolved:
        status = "degraded"
    elif excluded or not normalized:
        status = "degraded" if excluded else "skipped"
    else:
        status = "pass"
    return {
        "version": ADAPTATION_MONSTER_GUARDRAIL_VERSION,
        "status": status,
        "source_location": _safe_text(source_location, MAX_SEED_TEXT_CHARS),
        "canonical_vocabulary_count": len(vocabulary),
        "entries_seen": len(entries),
        "normalized_monsters": normalized[:MAX_NORMALIZED_MONSTER_RECORDS],
        "normalized_refs": [record["canonical_name"] for record in normalized[:MAX_NORMALIZED_MONSTER_RECORDS]],
        "excluded_entries": excluded[:MAX_EXCLUDED_MONSTER_RECORDS],
        "non_monster_entries": excluded[:MAX_EXCLUDED_MONSTER_RECORDS],
        "unresolved_entries": unresolved[:MAX_EXCLUDED_MONSTER_RECORDS],
        "contradiction_diagnostics": contradiction_diagnostics[:MAX_DIAGNOSTICS],
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }


def normalize_location_monsters(
    location_monsters: Any,
    canonical_vocabulary: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compatibility alias for adaptation location monster normalization."""
    return normalize_adaptation_location_monsters(
        location_monsters, canonical_vocabulary, **kwargs
    )


def _adaptation_dossier_mapping(dossier: Any) -> Mapping[str, Any]:
    """Return the validated dossier portion of an adaptation envelope."""
    if not isinstance(dossier, Mapping):
        return {}
    nested = dossier.get("dossier")
    return nested if isinstance(nested, Mapping) else dossier


def _named_seed_values(value: Any) -> List[str]:
    """Collect bounded names from a seed list without copying prose."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    names: List[str] = []
    for item in list(value)[:MAX_CANONICAL_MONSTER_VOCABULARY]:
        if isinstance(item, Mapping):
            name = item.get("name")
        else:
            name = item
        text = _safe_text(name, MAX_MONSTER_ENTRY_CHARS)
        if text and text not in names:
            names.append(text)
    return names


def _adaptation_area_paths(module_dir: str) -> List[str]:
    """Return active staged area paths in deterministic order."""
    areas_dir = os.path.join(module_dir, "areas")
    try:
        names = sorted(os.listdir(areas_dir))
    except OSError:
        return []
    excluded = ("_BU.json", ".bak", ".backup", ".tmp", "_backup.json")
    return [
        os.path.join(areas_dir, name)
        for name in names[:MAX_ADAPTATION_AREA_FILES]
        if name.endswith(".json") and not any(token in name for token in excluded)
    ]


def _adaptation_existing_monster_names(module_dir: str) -> List[str]:
    """Return bounded canonical names from staged monster filenames."""
    monsters_dir = os.path.join(module_dir, "monsters")
    try:
        names = sorted(os.listdir(monsters_dir))
    except OSError:
        return []
    excluded = ("_BU.json", ".bak", ".backup", ".tmp", "_backup.json")
    result: List[str] = []
    for filename in names:
        if not filename.endswith(".json") or any(token in filename for token in excluded):
            continue
        value = _safe_text(filename[:-5].replace("_", " "), MAX_MONSTER_ENTRY_CHARS)
        if value and value not in result:
            result.append(value)
        if len(result) >= MAX_CANONICAL_MONSTER_VOCABULARY:
            break
    return result


def _adaptation_known_scene_names(
    dossier: Mapping[str, Any],
    area_data: Sequence[Mapping[str, Any]],
) -> Tuple[List[str], List[str]]:
    """Collect bounded NPC and ally names for semantic exclusion."""
    npc_names = _named_seed_values(dossier.get("npc_seeds"))
    ally_names: List[str] = []
    for seed in list(dossier.get("npc_seeds") or [])[:MAX_CANONICAL_MONSTER_VOCABULARY]:
        if not isinstance(seed, Mapping):
            continue
        name = _safe_text(seed.get("name"), MAX_MONSTER_ENTRY_CHARS)
        role_text = " ".join(
            _safe_text(seed.get(field), MAX_MONSTER_ENTRY_CHARS)
            for field in ("role", "purpose", "disposition")
        ).lower()
        if name and any(token in role_text for token in ("ally", "helper", "friendly")):
            ally_names.append(name)

    for area in list(area_data)[:MAX_ADAPTATION_AREA_FILES]:
        locations = area.get("locations", [])
        if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes)):
            continue
        for location in list(locations)[:MAX_ADAPTATION_LOCATION_REPORTS]:
            if not isinstance(location, Mapping):
                continue
            raw_npcs = location.get("npcs", [])
            for name in _named_seed_values(raw_npcs):
                if name not in npc_names:
                    npc_names.append(name)
    return npc_names[:MAX_CANONICAL_MONSTER_VOCABULARY], ally_names[:MAX_CANONICAL_MONSTER_VOCABULARY]


def _append_adaptation_note(location: Dict[str, Any], note: str) -> None:
    """Preserve bounded semantic prose in the authored DM guidance field."""
    note = _safe_text(note, MAX_MONSTER_PROSE_CHARS)
    if not note:
        return
    existing = str(location.get("dmInstructions", "") or "")
    existing = existing.replace("\x00", " ").encode("ascii", "replace").decode("ascii")
    existing = _WHITESPACE_RE.sub(" ", existing).strip()
    if note in existing:
        return
    combined = "\n".join(part for part in (existing, note) if part)
    location["dmInstructions"] = combined


def normalize_adaptation_module_monsters(
    module_dir: Union[str, Path],
    dossier: Any,
    *,
    canonical_vocabulary: Any = None,
    canonical_registry: Any = None,
) -> Dict[str, Any]:
    """Normalize staged location monster entries before generic closure.

    Only canonical identities are retained in ``location.monsters``.  NPC,
    ally, ambiguous, and unmatched prose is removed from the structural list
    and preserved in bounded DM guidance plus the returned diagnostics.  Area
    changes use the repository's atomic JSON writer and are limited to the
    supplied staging tree.
    """
    try:
        root = os.fspath(module_dir)
    except TypeError:
        root = ""
    report: Dict[str, Any] = {
        "version": ADAPTATION_MONSTER_GUARDRAIL_VERSION,
        "status": "skipped",
        "areas_scanned": 0,
        "locations_scanned": 0,
        "entries_seen": 0,
        "normalized_refs": [],
        "excluded_entries": [],
        "unresolved_entries": [],
        "contradiction_diagnostics": [],
        "diagnostics": [],
        "files_changed": [],
    }
    if not root or not os.path.isdir(root):
        report["status"] = "blocked"
        report["diagnostics"].append(
            _diagnostic("adaptation_staging_missing", "adaptation staging directory was unavailable")
        )
        return report

    area_paths = _adaptation_area_paths(root)
    area_data: List[Mapping[str, Any]] = []
    loaded: List[Tuple[str, Dict[str, Any]]] = []
    for area_path in area_paths:
        payload = safe_read_json(area_path)
        if not isinstance(payload, dict):
            report["diagnostics"].append(
                _diagnostic("area_read_failed", "staged area was unreadable")
            )
            continue
        loaded.append((area_path, payload))
        area_data.append(payload)
    report["areas_scanned"] = len(loaded)

    dossier_mapping = _adaptation_dossier_mapping(dossier)
    source_refs = extract_adaptation_adversaries(dossier)
    existing_names = _adaptation_existing_monster_names(root)
    compendium = load_monster_compendium_lookup()
    compendium_names: List[str] = []
    for slug in sorted(compendium)[:MAX_CANONICAL_MONSTER_VOCABULARY]:
        payload = compendium.get(slug)
        name = payload.get("name") if isinstance(payload, Mapping) else None
        compendium_names.append(_safe_text(name or slug.replace("_", " "), MAX_MONSTER_ENTRY_CHARS))
    vocabulary = canonical_vocabulary
    if vocabulary is None:
        vocabulary = source_refs + existing_names + compendium_names
    known_npcs, known_allies = _adaptation_known_scene_names(dossier_mapping, area_data)

    changed = False
    for area_path, area in loaded:
        locations = area.get("locations", [])
        if not isinstance(locations, list):
            continue
        for location in locations[:MAX_ADAPTATION_LOCATION_REPORTS]:
            if not isinstance(location, dict) or "monsters" not in location:
                continue
            report["locations_scanned"] += 1
            source_location = _safe_text(
                location.get("locationName") or location.get("name") or location.get("locationId", ""),
                MAX_SEED_TEXT_CHARS,
            )
            normalized = normalize_adaptation_location_monsters(
                location.get("monsters"),
                vocabulary,
                canonical_registry=canonical_registry,
                source_location=source_location,
                known_npcs=known_npcs,
                known_allies=known_allies,
                approved_artifact_names=existing_names + compendium_names,
            )
            report["entries_seen"] += int(normalized.get("entries_seen", 0) or 0)
            report["normalized_refs"].extend(normalized.get("normalized_refs", []))
            report["excluded_entries"].extend(normalized.get("excluded_entries", []))
            report["unresolved_entries"].extend(normalized.get("unresolved_entries", []))
            report["contradiction_diagnostics"].extend(
                normalized.get("contradiction_diagnostics", [])
            )
            report["diagnostics"].extend(normalized.get("diagnostics", []))
            location["_adaptation_normalized_monsters"] = []
            for record in normalized.get("normalized_monsters", []):
                if not isinstance(record, Mapping):
                    continue
                quantity = record.get("quantity")
                if not isinstance(quantity, Mapping):
                    quantity = {"min": 1, "max": 1}
                structural = {
                    "name": _safe_text(record.get("canonical_name"), MAX_MONSTER_ENTRY_CHARS),
                    "quantity": {
                        "min": max(0, min(int(quantity.get("min", 1)), 999)),
                        "max": max(1, min(int(quantity.get("max", 1)), 999)),
                    },
                }
                if structural["quantity"]["max"] < structural["quantity"]["min"]:
                    structural["quantity"]["max"] = structural["quantity"]["min"]
                prose = _safe_text(record.get("descriptive_prose", ""), MAX_MONSTER_PROSE_CHARS)
                if prose:
                    _append_adaptation_note(
                        location,
                        f"Adaptation encounter detail ({structural['name']}): {prose}",
                    )
                location["_adaptation_normalized_monsters"].append(structural)
            notes = list(normalized.get("excluded_entries", [])) + list(
                normalized.get("unresolved_entries", [])
            )
            for record in notes[:MAX_ADAPTATION_PROSE_NOTES]:
                if isinstance(record, Mapping):
                    original = _safe_text(record.get("original_text", ""), MAX_MONSTER_ENTRY_CHARS)
                    reason = _safe_text(record.get("reason", ""), 96)
                    if original:
                        _append_adaptation_note(
                            location,
                            f"Adaptation monster note ({reason}): {original}",
                        )
            normalized_monsters = location.pop("_adaptation_normalized_monsters", None)
            if normalized_monsters is not None:
                location["monsters"] = normalized_monsters
                changed = True

    report["normalized_refs"] = list(dict.fromkeys(report["normalized_refs"]))[
        :MAX_NORMALIZED_MONSTER_RECORDS
    ]
    report["excluded_entries"] = report["excluded_entries"][:MAX_EXCLUDED_MONSTER_RECORDS]
    report["unresolved_entries"] = report["unresolved_entries"][:MAX_EXCLUDED_MONSTER_RECORDS]
    report["contradiction_diagnostics"] = report["contradiction_diagnostics"][:MAX_DIAGNOSTICS]
    report["diagnostics"] = report["diagnostics"][:MAX_DIAGNOSTICS]
    if report["unresolved_entries"]:
        report["status"] = "degraded"
    elif loaded:
        report["status"] = "pass"
    if changed:
        for area_path, area in loaded:
            if not safe_write_json(area_path, area, create_backup=False):
                report["status"] = "blocked"
                report["diagnostics"].append(
                    _diagnostic("area_atomic_write_failed", "normalized staged area could not be persisted")
                )
                continue
            report["files_changed"].append(_bounded_path(area_path))
    return report


def _append_adversary(
    value: Any,
    adversaries: List[str],
    seen: set[str],
    diagnostics: List[Dict[str, Any]],
    *,
    encounter_index: int,
) -> None:
    """Add one valid adversary in source order, subject to the global bound."""
    if not isinstance(value, str):
        diagnostics.append(
            _diagnostic(
                "invalid_adversary_value",
                "encounter adversary was ignored because it was not text",
                encounter_index=encounter_index,
            )
        )
        return

    text = _safe_text(value, MAX_ADVERSARY_CHARS)
    if not text:
        diagnostics.append(
            _diagnostic(
                "empty_adversary_value",
                "empty encounter adversary was ignored",
                encounter_index=encounter_index,
            )
        )
        return

    key = _adversary_key(text)
    if not key or key in seen:
        return
    if len(adversaries) >= MAX_ADAPTATION_ADVERSARIES:
        diagnostics.append(
            _diagnostic(
                "adversary_bound_reached",
                "additional encounter adversaries were ignored after the bound",
                encounter_index=encounter_index,
                adversary=text,
            )
        )
        return
    seen.add(key)
    adversaries.append(text)


def _sanitize_seed(
    seed: Mapping[str, Any],
    encounter_index: int,
    diagnostics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Copy only the bounded encounter fields needed by binding."""
    sanitized: Dict[str, Any] = {}
    scalar_fields = ("name", "setup", "stakes", "location", "source_basis")
    for field in scalar_fields:
        value = seed.get(field)
        if isinstance(value, str) and value.strip():
            sanitized[field] = _safe_text(value, MAX_SEED_TEXT_CHARS)

    resolution_paths = seed.get("resolution_paths")
    if isinstance(resolution_paths, Sequence) and not isinstance(
        resolution_paths, (str, bytes)
    ):
        sanitized_paths: List[str] = []
        for value in list(resolution_paths)[:MAX_SEED_LIST_ITEMS]:
            if isinstance(value, str) and value.strip():
                sanitized_paths.append(_safe_text(value, MAX_SEED_TEXT_CHARS))
        if sanitized_paths:
            sanitized["resolution_paths"] = sanitized_paths

    raw_adversaries = seed.get("adversaries")
    if isinstance(raw_adversaries, Sequence) and not isinstance(
        raw_adversaries, (str, bytes)
    ):
        sanitized_adversaries: List[str] = []
        for value in list(raw_adversaries)[:MAX_SEED_LIST_ITEMS]:
            if isinstance(value, str) and value.strip():
                sanitized_adversaries.append(
                    _safe_text(value, MAX_ADVERSARY_CHARS)
                )
        if sanitized_adversaries:
            sanitized["adversaries"] = sanitized_adversaries
    elif raw_adversaries is not None:
        diagnostics.append(
            _diagnostic(
                "invalid_adversaries_field",
                "encounter adversaries field was ignored because it was not a list",
                encounter_index=encounter_index,
            )
        )
    return sanitized


def _extract_adaptation_adversary_data(
    dossier: Any,
) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """Extract bounded adversaries and sanitized encounter seeds."""
    if not isinstance(dossier, Mapping):
        return [], [], [
            _diagnostic(
                "invalid_dossier_input",
                "adaptation dossier was not a mapping; monster guardrail skipped",
            )
        ], False

    # Handoffs may wrap the validated dossier.  Only the known dossier object
    # is inspected; arbitrary envelope fields are never copied to the report.
    candidate: Mapping[str, Any] = dossier
    nested = dossier.get("dossier")
    if isinstance(nested, Mapping):
        candidate = nested

    encounter_seeds = candidate.get("encounter_seeds")
    if encounter_seeds is None:
        return [], [], [
            _diagnostic(
                "encounter_seeds_missing",
                "adaptation dossier has no encounter seeds; monster guardrail skipped",
            )
        ], False
    if not isinstance(encounter_seeds, Sequence) or isinstance(
        encounter_seeds, (str, bytes)
    ):
        return [], [], [
            _diagnostic(
                "invalid_encounter_seeds",
                "adaptation encounter_seeds was not a list; monster guardrail skipped",
            )
        ], False

    adversaries: List[str] = []
    seen: set[str] = set()
    seeds: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    raw_seeds = list(encounter_seeds)
    if len(raw_seeds) > MAX_ADAPTATION_ENCOUNTERS:
        diagnostics.append(
            _diagnostic(
                "encounter_bound_reached",
                "additional encounter seeds were ignored after the bound",
            )
        )

    for encounter_index, raw_seed in enumerate(
        raw_seeds[:MAX_ADAPTATION_ENCOUNTERS]
    ):
        if not isinstance(raw_seed, Mapping):
            diagnostics.append(
                _diagnostic(
                    "invalid_encounter_seed",
                    "encounter seed was ignored because it was not an object",
                    encounter_index=encounter_index,
                )
            )
            continue
        seed = _sanitize_seed(raw_seed, encounter_index, diagnostics)
        seeds.append(seed)
        raw_adversaries = raw_seed.get("adversaries")
        if isinstance(raw_adversaries, Sequence) and not isinstance(
            raw_adversaries, (str, bytes)
        ):
            for value in list(raw_adversaries)[:MAX_SEED_LIST_ITEMS]:
                _append_adversary(
                    value,
                    adversaries,
                    seen,
                    diagnostics,
                    encounter_index=encounter_index,
                )
        elif raw_adversaries is not None:
            # _sanitize_seed already recorded this shape error.
            continue

    return adversaries, seeds, diagnostics, True


def extract_adaptation_adversaries(dossier: Any) -> List[str]:
    """Return bounded, ordered, deduplicated dossier adversary names.

    Malformed optional input returns an empty list.  The full orchestration
    report retains bounded diagnostics for operators that need the reason.
    """
    adversaries, _seeds, _diagnostics, _usable = (
        _extract_adaptation_adversary_data(dossier)
    )
    return adversaries


def _source_candidate_records(
    source: Any,
    source_label: str,
) -> List[Dict[str, Any]]:
    """Extract only explicit source adversary fields from one bounded mapping.

    Normalized packet ``monster_refs`` and adversary fields nested in explicit
    encounter seeds are source evidence.  Free-form encounter seed strings,
    descriptions, and generated prose are intentionally not interpreted as
    adversary names.
    """
    if not isinstance(source, Mapping):
        return []

    records: List[Dict[str, Any]] = []

    def _append(value: Any, field_ref: str, encounter_index: Optional[int] = None) -> None:
        if not isinstance(value, str):
            return
        text = _safe_text(value, MAX_ADVERSARY_CHARS)
        if not text:
            return
        record: Dict[str, Any] = {
            "name": text,
            "source_field": field_ref,
        }
        if encounter_index is not None:
            record["encounter_index"] = encounter_index
        records.append(record)

    def _append_list(value: Any, field_ref: str, encounter_index: Optional[int] = None) -> None:
        if isinstance(value, str):
            _append(value, field_ref, encounter_index)
            return
        if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
            return
        for index, item in enumerate(list(value)[:MAX_SOURCE_RECONCILIATION_CANDIDATES]):
            item_ref = f"{field_ref}[{index}]"
            if isinstance(item, Mapping):
                _append(
                    item.get("name", item.get("monster", item.get("creature", ""))),
                    item_ref + ".name",
                    encounter_index,
                )
            else:
                _append(item, item_ref, encounter_index)

    # normalized_packet.monster_refs is advisory extraction evidence, not an
    # authoritative encounter-adversary field.  In particular, source lore
    # commonly contains NPCs, roles, and creatures mentioned in prose.  Keep
    # the evidence available to the bounded reconciliation report, but never
    # promote it into the validated dossier's encounter seeds.
    if source_label != "normalized_packet":
        _append_list(source.get("monster_refs"), f"{source_label}.monster_refs")
    _append_list(source.get("adversaries"), f"{source_label}.adversaries")

    encounter_seeds = source.get("encounter_seeds")
    if isinstance(encounter_seeds, Sequence) and not isinstance(
        encounter_seeds, (bytes, str)
    ):
        for encounter_index, seed in enumerate(
            list(encounter_seeds)[:MAX_ADAPTATION_ENCOUNTERS]
        ):
            if not isinstance(seed, Mapping):
                # A source seed string is narrative evidence, not an identity.
                continue
            for field in ("adversaries", "monster_refs", "monsters", "creatures"):
                if field in seed:
                    _append_list(
                        seed.get(field),
                        f"{source_label}.encounter_seeds[{encounter_index}].{field}",
                        encounter_index,
                    )
    return records[:MAX_SOURCE_RECONCILIATION_CANDIDATES]


def _registry_dossier_mapping(value: Any) -> Mapping[str, Any]:
    """Return the bounded dossier object used by the registry seam."""
    if not isinstance(value, Mapping):
        return {}
    nested = value.get("dossier")
    return nested if isinstance(nested, Mapping) else value


def _registry_reference_text(value: Any) -> str:
    """Extract one raw reference without turning prose into an identity."""
    if isinstance(value, str):
        return _safe_text(value, MAX_ADVERSARY_CHARS)
    if isinstance(value, Mapping):
        return _safe_text(
            value.get("name", value.get("monster", value.get("creature", ""))),
            MAX_ADVERSARY_CHARS,
        )
    return ""


def _registry_artifact_candidates(
    roots: Sequence[Any],
) -> List[Dict[str, Any]]:
    """Read explicitly supplied staging/reusable roots, never write them."""
    candidates: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()
    for supplied_root in list(roots)[:MAX_SOURCE_RECONCILIATION_CANDIDATES]:
        for root in _normalize_reusable_root_candidates(supplied_root):
            monsters_dir = (
                root
                if os.path.basename(os.path.normpath(root)) == "monsters"
                else os.path.join(root, "monsters")
            )
            try:
                filenames = sorted(os.listdir(monsters_dir))
            except OSError:
                continue
            for filename in filenames:
                if not filename.endswith(".json") or any(
                    token in filename
                    for token in ("_BU.json", ".bak", ".backup", ".tmp")
                ):
                    continue
                path = os.path.join(monsters_dir, filename)
                if path in seen_paths or os.path.islink(path):
                    continue
                seen_paths.add(path)
                payload, reason, _missing = _load_monster_artifact(path)
                if reason != "schema_sufficient":
                    continue
                payload_name = (
                    payload.get("name") if isinstance(payload, Mapping) else ""
                )
                label = _safe_text(
                    payload_name or filename[:-5].replace("_", " "),
                    MAX_ADVERSARY_CHARS,
                )
                if label:
                    candidates.append(
                        {
                            "name": label,
                            "path": _bounded_path(path),
                            "source": "staging" if os.path.abspath(root) == os.path.abspath(str(supplied_root)) else "reusable",
                        }
                    )
                if len(candidates) >= MAX_IDENTITY_REGISTRY_ENTRIES:
                    return candidates
    return candidates


def _registry_area_inputs(
    areas: Any,
    module_dir: Optional[Union[str, Path]],
) -> List[Mapping[str, Any]]:
    """Return explicit area objects or read-only active staged area files."""
    if isinstance(areas, Sequence) and not isinstance(areas, (str, bytes)):
        return [item for item in list(areas) if isinstance(item, Mapping)]
    if isinstance(areas, Mapping):
        return [areas]
    if not module_dir:
        return []
    result: List[Mapping[str, Any]] = []
    for path in _adaptation_area_paths(os.fspath(module_dir)):
        payload = safe_read_json(path)
        if isinstance(payload, Mapping):
            result.append(payload)
    return result


def _registry_quantity_evidence(
    raw_entry: Any,
    *,
    source: str,
    raw_reference: str,
    location_id: str = "",
    encounter_reference: str = "",
) -> Optional[Dict[str, Any]]:
    """Extract quantity as evidence, deliberately separate from identity."""
    _name, _description, quantity = _entry_payload(raw_entry)
    quantity_hint = ""
    if quantity is None:
        _remainder, quantity_hint, quantity_value = _strip_quantity_prefix(raw_reference)
        if quantity_value is not None:
            quantity = {"min": quantity_value, "max": quantity_value}
    if quantity is None:
        return None
    evidence: Dict[str, Any] = {
        "quantity": quantity,
        "source": _safe_text(source, 180),
        "raw_reference": raw_reference,
    }
    if quantity_hint:
        evidence["quantity_hint"] = _safe_text(quantity_hint, MAX_QUANTITY_CHARS)
    if location_id:
        evidence["location_id"] = location_id
    if encounter_reference:
        evidence["encounter_reference"] = encounter_reference
    return evidence


def build_adaptation_canonical_monster_registry(
    dossier: Any,
    *,
    source_packet: Any = None,
    builder_input: Any = None,
    areas: Any = None,
    module_dir: Optional[Union[str, Path]] = None,
    staging_root: Optional[Union[str, Path]] = None,
    reusable_module_dirs: Optional[Sequence[Union[str, Path]]] = None,
    approved_canonical_identities: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Build the provider-free, adaptation-only monster identity registry.

    This is an in-memory/read-only contract seam.  It records raw labels and
    source evidence separately from Python-owned canonical identities so later
    normalization, materialization, binding, and revision stages can consume
    one deterministic registry.  It does not modify the dossier, areas, or
    any artifact tree, and it never promotes advisory prose into approval.
    """
    dossier_map = _registry_dossier_mapping(dossier)
    if dossier_map.get("adaptation_mode") != "llm_adaptation":
        return {
            "version": ADAPTATION_MONSTER_IDENTITY_REGISTRY_VERSION,
            "status": "skipped",
            "adaptation_only": True,
            "approved_identities": [],
            "entries": [],
            "unresolved_references": [],
            "diagnostics": [{"code": "legacy_route_isolated"}],
        }

    approved_sources: List[Tuple[str, str]] = []

    def add_approved(value: Any, source: str) -> None:
        text = _registry_reference_text(value)
        if text:
            approved_sources.append((text, _safe_text(source, 180)))

    for index, value in enumerate(dossier_map.get("approved_monster_identities", []) or []):
        add_approved(value, f"dossier.approved_monster_identities[{index}]")
    for index, value in enumerate(dossier_map.get("canonical_monster_identities", []) or []):
        add_approved(value, f"dossier.canonical_monster_identities[{index}]")

    raw_seeds = dossier_map.get("encounter_seeds", [])
    if isinstance(raw_seeds, Sequence) and not isinstance(raw_seeds, (str, bytes)):
        for encounter_index, seed in enumerate(list(raw_seeds)[:MAX_ADAPTATION_ENCOUNTERS]):
            if not isinstance(seed, Mapping):
                continue
            for ref_index, value in enumerate(seed.get("adversaries", []) or []):
                add_approved(value, f"dossier.encounter_seeds[{encounter_index}].adversaries[{ref_index}]")

    for source_label, source in (("source_packet", source_packet), ("builder_input", builder_input)):
        if not isinstance(source, Mapping):
            continue
        for field in ("approved_monster_identities", "canonical_monster_identities", "adversaries"):
            values = source.get(field, [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                for index, value in enumerate(list(values)[:MAX_SOURCE_RECONCILIATION_CANDIDATES]):
                    add_approved(value, f"{source_label}.{field}[{index}]")

    artifact_roots: List[Any] = []
    if staging_root:
        artifact_roots.append(staging_root)
    artifact_roots.extend(list(reusable_module_dirs or []))
    artifacts = _registry_artifact_candidates(artifact_roots)
    for artifact in artifacts:
        add_approved(artifact["name"], f"{artifact['source']}.artifact")

    # First establish canonical identities from Python-owned approved sources.
    identities: Dict[str, Dict[str, Any]] = {}
    for raw_label, approval_source in approved_sources[:MAX_IDENTITY_REGISTRY_ENTRIES]:
        identity = _adaptation_identity_variants(raw_label)
        key = _adaptation_canonical_identity_key(identity)
        if not key:
            continue
        canonical_name = _adaptation_identity_display_name(key)
        slug = _canonical_monster_slug(canonical_name)
        entry = identities.setdefault(
            slug,
            {
                "canonical_identity": canonical_name,
                "canonical_slug": slug,
                "approved": True,
                "aliases": [],
                "raw_references": [],
                "approval_provenance": [],
                "affected_location_ids": [],
                "encounter_references": [],
                "quantity_evidence": [],
                "reusable_artifacts": [],
            },
        )
        if raw_label != canonical_name and raw_label not in entry["aliases"]:
            entry["aliases"].append(raw_label)
        if raw_label not in entry["raw_references"]:
            entry["raw_references"].append(raw_label)
        provenance = {"source": approval_source, "raw_label": raw_label}
        if provenance not in entry["approval_provenance"]:
            entry["approval_provenance"].append(provenance)

    for artifact in artifacts:
        slug = _canonical_monster_slug(artifact["name"])
        entry = identities.get(slug)
        if entry is None:
            continue
        entry["reusable_artifacts"].append(artifact)

    unresolved: List[Dict[str, Any]] = []

    def attach_reference(raw_entry: Any, *, source: str, location_id: str = "", encounter_reference: str = "") -> None:
        raw_reference = _registry_reference_text(raw_entry)
        if not raw_reference:
            return
        vocabulary = [
            (
                entry["canonical_identity"],
                list(
                    dict.fromkeys(
                        [
                            * _adaptation_identity_variants(
                                entry["canonical_identity"]
                            ).get("variants", []),
                            entry["canonical_slug"],
                            *entry["aliases"],
                            entry["canonical_identity"],
                        ]
                    )
                ),
            )
            for entry in identities.values()
        ]
        canonical_name, _indexes, match_status = _find_canonical_match(raw_reference, vocabulary)
        if not canonical_name:
            identity = _adaptation_identity_variants(raw_reference)
            slug = _canonical_monster_slug(_adaptation_identity_display_name(_adaptation_canonical_identity_key(identity)))
            entry = identities.get(slug)
            canonical_name = entry["canonical_identity"] if entry else None
        if not canonical_name:
            unresolved.append({"raw_reference": raw_reference, "source": _safe_text(source, 180), "location_id": location_id, "encounter_reference": encounter_reference, "reason": match_status})
            return
        entry = identities[_canonical_monster_slug(canonical_name)]
        if raw_reference not in entry["raw_references"]:
            entry["raw_references"].append(raw_reference)
        if raw_reference != entry["canonical_identity"] and raw_reference not in entry["aliases"]:
            entry["aliases"].append(raw_reference)
        if location_id and location_id not in entry["affected_location_ids"]:
            entry["affected_location_ids"].append(location_id)
        if encounter_reference and encounter_reference not in entry["encounter_references"]:
            entry["encounter_references"].append(encounter_reference)
        quantity = _registry_quantity_evidence(raw_entry, source=source, raw_reference=raw_reference, location_id=location_id, encounter_reference=encounter_reference)
        if quantity and quantity not in entry["quantity_evidence"]:
            entry["quantity_evidence"].append(quantity)

    for encounter_index, seed in enumerate(list(raw_seeds)[:MAX_ADAPTATION_ENCOUNTERS] if isinstance(raw_seeds, Sequence) and not isinstance(raw_seeds, (str, bytes)) else []):
        if not isinstance(seed, Mapping):
            continue
        encounter_reference = _safe_text(seed.get("encounterId", seed.get("id", seed.get("name", f"encounter_{encounter_index}"))), 180)
        for value in seed.get("adversaries", []) or []:
            attach_reference(value, source=f"dossier.encounter_seeds[{encounter_index}]", encounter_reference=encounter_reference)

    for area_index, area in enumerate(_registry_area_inputs(areas, module_dir)):
        area_id = _safe_text(area.get("areaId", area.get("id", f"area_{area_index}")), 96)
        for location_index, location in enumerate(area.get("locations", []) or []):
            if not isinstance(location, Mapping):
                continue
            location_id = _safe_text(location.get("locationId", location.get("id", location.get("name", f"location_{location_index}"))), 128)
            for value in location.get("monsters", []) or []:
                attach_reference(value, source=f"area[{area_index}].location[{location_index}]", location_id=location_id or area_id)

    for entry in identities.values():
        entry["aliases"] = sorted(set(entry["aliases"]))[:MAX_IDENTITY_REGISTRY_ALIASES]
        entry["raw_references"] = sorted(set(entry["raw_references"]))[:MAX_IDENTITY_REGISTRY_PROVENANCE]
        entry["approval_provenance"] = sorted(entry["approval_provenance"], key=lambda item: (item.get("source", ""), item.get("raw_label", "")))[:MAX_IDENTITY_REGISTRY_PROVENANCE]
        entry["affected_location_ids"] = sorted(set(entry["affected_location_ids"]))[:MAX_IDENTITY_REGISTRY_LOCATIONS]
        entry["encounter_references"] = sorted(set(entry["encounter_references"]))[:MAX_IDENTITY_REGISTRY_ENCOUNTERS]
        entry["quantity_evidence"] = sorted(entry["quantity_evidence"], key=lambda item: (item.get("location_id", ""), item.get("encounter_reference", ""), item.get("raw_reference", "")))[:MAX_IDENTITY_REGISTRY_QUANTITIES]
        entry["reusable_artifacts"] = sorted(entry["reusable_artifacts"], key=lambda item: item.get("path", ""))[:MAX_IDENTITY_REGISTRY_PROVENANCE]

    ordered_entries = [identities[key] for key in sorted(identities)]
    return {
        "version": ADAPTATION_MONSTER_IDENTITY_REGISTRY_VERSION,
        "status": "pass" if not unresolved else "degraded",
        "adaptation_only": True,
        "approved_identities": [entry["canonical_identity"] for entry in ordered_entries],
        "entries": ordered_entries[:MAX_IDENTITY_REGISTRY_ENTRIES],
        "unresolved_references": sorted(unresolved, key=lambda item: (item.get("raw_reference", ""), item.get("source", "")))[:MAX_IDENTITY_REGISTRY_PROVENANCE],
        "diagnostics": [],
    }


# Explicit aliases make the registry seam discoverable without coupling later
# pipeline work to a particular helper spelling.
build_adaptation_monster_identity_registry = build_adaptation_canonical_monster_registry
build_adaptation_canonical_registry = build_adaptation_canonical_monster_registry


def build_effective_adaptation_guardrail_input(
    dossier: Any,
    *,
    source_packet: Any = None,
    builder_input: Any = None,
    accepted_finalization_operation: Any = None,
) -> Dict[str, Any]:
    """Reconcile missing dossier adversaries from authoritative source fields.

    The returned effective input is an in-memory copy.  The validated dossier
    artifact remains unchanged because its schema intentionally has no
    reconciliation metadata fields.  Provenance is therefore returned as a
    bounded report for the build result.  Only explicit normalized-packet or
    builder-input source fields are considered; encounter prose is never
    promoted to a monster identity.
    """
    effective_input = deepcopy(dossier) if isinstance(dossier, Mapping) else {}
    effective_dossier: Mapping[str, Any]
    if isinstance(effective_input.get("dossier"), Mapping):
        effective_dossier = effective_input["dossier"]
    else:
        effective_dossier = effective_input

    report: Dict[str, Any] = {
        "version": ADAPTATION_SOURCE_RECONCILIATION_VERSION,
        "status": "unchanged",
        "source_reconciled": False,
        "source_fields": [],
        "appended_adversaries": [],
        "already_present": [],
        "ignored_source_candidates": [],
        "diagnostics": [],
    }
    if not isinstance(effective_dossier, Mapping):
        report["status"] = "blocked"
        report["diagnostics"].append(
            {"code": "invalid_dossier_input", "message": "dossier was not a mapping"}
        )
        return {
            "effective_dossier": effective_dossier,
            "effective_guardrail_input": effective_input,
            "reconciliation_report": report,
        }
    if effective_dossier.get("adaptation_mode") != "llm_adaptation":
        # The helper is an adaptation-only remediation boundary.  Legacy
        # dossiers and source packets must remain byte-for-byte untouched.
        return {
            "effective_dossier": effective_dossier,
            "effective_guardrail_input": effective_input,
            "reconciliation_report": report,
        }

    # An accepted monster operation is a bounded identity handoff, not a
    # dossier patch.  Apply it only to the in-memory effective input used by
    # the next fresh build so the persisted prior dossier remains immutable.
    operation = accepted_finalization_operation
    if isinstance(operation, Mapping) and operation.get("operation") == "resolve_monster_reference":
        target = operation.get("target")
        if isinstance(target, Mapping):
            reference_key = target.get("reference_key")
            canonical_identity = target.get("canonical_identity")
            if isinstance(reference_key, str) and isinstance(canonical_identity, str):
                seeds = effective_dossier.get("encounter_seeds")
                if isinstance(seeds, list):
                    for seed in seeds:
                        if not isinstance(seed, dict):
                            continue
                        adversaries = seed.get("adversaries")
                        if not isinstance(adversaries, list):
                            continue
                        seed["adversaries"] = [
                            canonical_identity if _adversary_key(value) == _adversary_key(reference_key) else value
                            for value in adversaries
                        ]

    sources: List[Tuple[str, Mapping[str, Any]]] = []
    if isinstance(source_packet, Mapping):
        nested_packet = source_packet.get("normalized_packet")
        if isinstance(nested_packet, Mapping):
            sources.append(("normalized_packet", nested_packet))
        else:
            sources.append(("normalized_packet", source_packet))
    if isinstance(builder_input, Mapping):
        sources.append(("builder_input", builder_input))

    dossier_hash = str(effective_dossier.get("source_hash") or "").strip().lower()
    source_hashes: List[Tuple[str, str]] = []
    for label, source in sources:
        candidate_hash = str(source.get("source_hash") or "").strip().lower()
        if candidate_hash:
            source_hashes.append((f"{label}.source_hash", candidate_hash))
        identity = source.get("packet_identity")
        if isinstance(identity, Mapping):
            identity_hash = str(identity.get("source_hash") or "").strip().lower()
            if identity_hash:
                source_hashes.append((f"{label}.packet_identity.source_hash", identity_hash))

    mismatched_hashes = [
        (field_ref, value)
        for field_ref, value in source_hashes
        if dossier_hash and value != dossier_hash
    ]
    if mismatched_hashes:
        report["status"] = "blocked"
        report["diagnostics"].append(
            {
                "code": "source_hash_mismatch",
                "message": "source evidence did not match the adaptation dossier hash",
                "source_field": mismatched_hashes[0][0],
            }
        )
        return {
            "effective_dossier": effective_dossier,
            "effective_guardrail_input": effective_input,
            "reconciliation_report": report,
        }

    candidates: List[Dict[str, Any]] = []
    for label, source in sources:
        candidates.extend(_source_candidate_records(source, label))
    candidates = candidates[:MAX_SOURCE_RECONCILIATION_CANDIDATES]

    # Preserve advisory packet extraction without allowing it to become a
    # combatant identity.  This list is intentionally bounded and records the
    # exact source field for operator diagnostics.
    for label, source in sources:
        if label != "normalized_packet":
            continue
        advisory = source.get("monster_refs")
        if isinstance(advisory, str):
            advisory = [advisory]
        if not isinstance(advisory, Sequence) or isinstance(advisory, (str, bytes)):
            continue
        for index, value in enumerate(list(advisory)[:MAX_SOURCE_RECONCILIATION_CANDIDATES]):
            if not isinstance(value, str) or not value.strip():
                continue
            report["ignored_source_candidates"].append(
                {
                    "name": _safe_text(value, MAX_ADVERSARY_CHARS),
                    "source_reconciled": False,
                    "source_field": f"{label}.monster_refs[{index}]",
                    "reason": "advisory_source_candidate_not_authoritative",
                }
            )
    report["ignored_source_candidates"] = report["ignored_source_candidates"][
        :MAX_SOURCE_RECONCILIATION_CANDIDATES
    ]
    if not candidates:
        report["status"] = "unchanged"
        return {
            "effective_dossier": effective_dossier,
            "effective_guardrail_input": effective_input,
            "reconciliation_report": report,
        }

    encounter_seeds = effective_dossier.get("encounter_seeds")
    if not isinstance(encounter_seeds, list):
        report["status"] = "blocked"
        report["diagnostics"].append(
            {
                "code": "encounter_seeds_unavailable",
                "message": "source adversaries could not be attached to dossier encounter seeds",
            }
        )
        return {
            "effective_dossier": effective_dossier,
            "effective_guardrail_input": effective_input,
            "reconciliation_report": report,
        }

    existing_keys = {
        _adversary_key(value)
        for seed in encounter_seeds
        if isinstance(seed, Mapping)
        for value in (seed.get("adversaries") or [])
        if isinstance(value, str)
    }
    seen_source_keys: set[str] = set()
    first_mapping_index = next(
        (index for index, seed in enumerate(encounter_seeds) if isinstance(seed, Mapping)),
        None,
    )
    for candidate in candidates:
        name = candidate.get("name", "")
        key = _adversary_key(name)
        if not key or key in seen_source_keys:
            continue
        seen_source_keys.add(key)
        source_field = _safe_text(candidate.get("source_field", ""), 180)
        encounter_index = candidate.get("encounter_index")
        target_index = (
            encounter_index
            if isinstance(encounter_index, int)
            and 0 <= encounter_index < len(encounter_seeds)
            and isinstance(encounter_seeds[encounter_index], Mapping)
            else first_mapping_index
        )
        if key in existing_keys:
            report["already_present"].append(
                {"name": name, "source_reconciled": False, "source_field": source_field}
            )
            continue
        if target_index is None:
            report["ignored_source_candidates"].append(
                {
                    "name": name,
                    "source_reconciled": False,
                    "source_field": source_field,
                    "reason": "no_mapping_encounter_seed",
                }
            )
            continue
        target_seed = encounter_seeds[target_index]
        adversaries = target_seed.get("adversaries")
        if not isinstance(adversaries, list):
            adversaries = []
            target_seed["adversaries"] = adversaries
        adversaries.append(name)
        existing_keys.add(key)
        report["appended_adversaries"].append(
            {
                "name": name,
                "encounter_index": target_index,
                "source_reconciled": True,
                "source_field": source_field,
            }
        )

    report["source_fields"] = [
        _safe_text(candidate.get("source_field", ""), 180)
        for candidate in candidates[:MAX_SOURCE_RECONCILIATION_CANDIDATES]
        if candidate.get("source_field")
    ][:MAX_SOURCE_RECONCILIATION_CANDIDATES]
    report["already_present"] = report["already_present"][:MAX_SOURCE_RECONCILIATION_CANDIDATES]
    report["appended_adversaries"] = report["appended_adversaries"][
        :MAX_SOURCE_RECONCILIATION_CANDIDATES
    ]
    report["ignored_source_candidates"] = report["ignored_source_candidates"][
        :MAX_SOURCE_RECONCILIATION_CANDIDATES
    ]
    report["source_reconciled"] = bool(report["appended_adversaries"])
    if report["source_reconciled"]:
        report["status"] = "reconciled"
    report["diagnostics"] = report["diagnostics"][:MAX_SOURCE_RECONCILIATION_DIAGNOSTICS]
    return {
        "effective_dossier": effective_dossier,
        "effective_guardrail_input": effective_input,
        "reconciliation_report": report,
    }


def _skipped_report(
    diagnostics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return the stable empty report shape."""
    return {
        "version": ADAPTATION_MONSTER_GUARDRAIL_VERSION,
        "report_version": ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION,
        "status": "skipped",
        "adversaries": [],
        "adversaries_planned": 0,
        "monsters_planned": 0,
        "monsters_reused": 0,
        "monsters_generated": 0,
        "monsters_unresolved": 0,
        "monsters_excluded": 0,
        "encounters_planned": 0,
        "encounters_bound": 0,
        "encounters_scene_resolved": 0,
        "encounters_unresolved": 0,
        "encounters_unbound": 0,
        "unresolved_refs": [],
        "non_monster_refs": [],
        "unresolved_diagnostics": [],
        "encounter_bindings": [],
        "resolution_diagnostics": [],
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
        "generation_policy": {
            "enabled": False,
            "reason": "not_applicable",
            "explicit_opt_in": False,
            "timeout_seconds": None,
        },
    }


def _resolution_identity_provenance(
    reference: Any,
    canonical_slug: Any,
    source: Any,
    reason: Any,
) -> Dict[str, Any]:
    """Build bounded raw/canonical identity provenance for one report row."""
    raw_reference = _safe_text(reference, MAX_ADVERSARY_CHARS)
    identity = _adaptation_identity_variants(raw_reference)
    slug = _canonical_monster_slug(canonical_slug)
    if not slug:
        slug = _canonical_monster_slug(
            _adaptation_canonical_identity_key(identity)
        )
    canonical_identity = _safe_text(slug, MAX_ADVERSARY_CHARS)
    canonical_name = _safe_text(slug.replace("_", " "), MAX_ADVERSARY_CHARS)
    raw_slug = _canonical_monster_slug(raw_reference)
    resolution_reason = _safe_text(reason, 96)
    resolution_variant = (
        "exact_raw"
        if raw_slug and raw_slug == slug
        else "folded_canonical"
    )
    return {
        "raw_reference": raw_reference,
        "canonical_identity": canonical_identity,
        "canonical_name": canonical_name,
        "identity_variants": [
            _safe_text(value, MAX_ADVERSARY_CHARS)
            for value in identity.get("variants", [])
            if isinstance(value, str) and value
        ][:MAX_RESOLUTION_IDENTITY_VARIANTS],
        "selected_resolution_variant": resolution_variant,
        "resolution_source": _safe_text(source, 32),
        "resolution_reason": resolution_reason,
    }


def _safe_resolution_attempts(value: Any) -> List[Dict[str, Any]]:
    """Project attempts to the bounded, provider-free report contract."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    safe_attempts: List[Dict[str, Any]] = []
    for attempt in list(value)[:MAX_MATERIALIZATION_ATTEMPTS]:
        if not isinstance(attempt, Mapping):
            continue
        projected: Dict[str, Any] = {}
        for key, limit in (
            ("source", 32),
            ("status", 32),
            ("path", MAX_ARTIFACT_PATH_CHARS),
            ("reason", 96),
        ):
            if attempt.get(key) not in (None, ""):
                projected[key] = _safe_text(attempt.get(key), limit)
        missing = attempt.get("missing_required_fields")
        if isinstance(missing, Sequence) and not isinstance(missing, (str, bytes)):
            projected["missing_required_fields"] = [
                _safe_text(field, 64) for field in list(missing)[:8]
            ]
        safe_attempts.append(projected)
    return safe_attempts


def _safe_encounter_bindings(value: Any) -> List[Dict[str, Any]]:
    """Project encounter bindings without copying source/provider payloads."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    safe_bindings: List[Dict[str, Any]] = []
    allowed_seed_fields = ("name", "location", "source_basis", "setup", "stakes")
    for binding in list(value)[:MAX_ADAPTATION_ENCOUNTERS]:
        if not isinstance(binding, Mapping):
            continue
        projected: Dict[str, Any] = {}
        for key, limit in (
            ("status", 32),
            ("monster_ref", MAX_ADVERSARY_CHARS),
            ("artifact_path", MAX_ARTIFACT_PATH_CHARS),
            ("reason", 96),
        ):
            if binding.get(key) not in (None, ""):
                projected[key] = _safe_text(binding.get(key), limit)
        unresolved = binding.get("unresolved_refs")
        if isinstance(unresolved, Sequence) and not isinstance(unresolved, (str, bytes)):
            projected["unresolved_refs"] = [
                _safe_text(ref, MAX_ADVERSARY_CHARS)
                for ref in list(unresolved)[:MAX_ADAPTATION_ADVERSARIES]
            ]
        seed = binding.get("seed")
        if isinstance(seed, Mapping):
            safe_seed: Dict[str, Any] = {}
            for field in allowed_seed_fields:
                if isinstance(seed.get(field), str) and seed.get(field).strip():
                    safe_seed[field] = _safe_text(seed[field], MAX_SEED_TEXT_CHARS)
            adversaries = seed.get("adversaries")
            if isinstance(adversaries, Sequence) and not isinstance(adversaries, (str, bytes)):
                safe_seed["adversaries"] = [
                    _safe_text(item, MAX_ADVERSARY_CHARS)
                    for item in list(adversaries)[:MAX_ADAPTATION_ADVERSARIES]
                    if isinstance(item, str)
                ]
            projected["seed"] = safe_seed
        safe_bindings.append(projected)
    return safe_bindings


def build_adaptation_monster_guardrail_report(
    dossier: Any,
    module_dir: Optional[Union[str, Path]] = None,
    *,
    staging_root: Optional[Union[str, Path]] = None,
    source_module_dir: Optional[Union[str, Path]] = None,
    reusable_module_dirs: Optional[Sequence[Union[str, Path]]] = None,
    source_module_name: Optional[str] = None,
    compendium_path: Optional[Union[str, Path]] = None,
    compendium_lookup: Optional[Mapping[str, Any]] = None,
    allow_generation: bool = False,
    monster_builder_path: Optional[Union[str, Path]] = None,
    generation_timeout_seconds: Any = DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS,
    additional_canonical_refs: Optional[Sequence[Any]] = None,
    generation_context: Optional[Mapping[str, Any]] = None,
    generation_opt_in: Optional[bool] = None,
    generation_gate_reason: Optional[str] = None,
    approved_canonical_refs: Optional[Sequence[Any]] = None,
    canonical_registry: Any = None,
) -> Dict[str, Any]:
    """Resolve dossier adversaries and return a deterministic guardrail report.

    ``module_dir`` remains the positional compatibility argument and acts as
    the staging root when ``staging_root`` is omitted.  New adaptation callers
    should pass ``staging_root`` explicitly and may provide source module,
    reusable module, or compendium locations separately. Generation is
    opt-in and remains bounded to the explicit staging root.
    """
    adversaries, seeds, diagnostics, usable = _extract_adaptation_adversary_data(
        dossier
    )
    if not usable or not seeds:
        return _skipped_report(diagnostics)

    resolution_dir = os.fspath(
        staging_root if staging_root is not None else module_dir
    ) if (staging_root is not None or module_dir is not None) else _SAFE_MISSING_MODULE_DIR
    effective_source_module_dir = source_module_dir
    if (
        effective_source_module_dir is None
        and staging_root is not None
        and module_dir is not None
    ):
        effective_source_module_dir = module_dir
    if module_dir is None and staging_root is None and adversaries:
        diagnostics.append(
            _diagnostic(
                "module_directory_missing",
                "module directory was not supplied; artifact resolution is expected to degrade",
            )
        )

    if canonical_registry is None and approved_canonical_refs is not None:
        canonical_registry = build_adaptation_canonical_monster_registry(
            dossier,
            areas=None,
            module_dir=module_dir,
            staging_root=staging_root,
            reusable_module_dirs=reusable_module_dirs,
            approved_canonical_identities=approved_canonical_refs,
        )

    # Adaptation normalization may discover canonical identities in generated
    # location data that are not present in the dossier encounter seeds.  Only
    # callers that have already normalized those identities may provide them;
    # raw generated prose must never enter this merge point.
    merged_adversaries = list(adversaries)
    seen_adversary_slugs = {
        _canonical_monster_slug(value) for value in merged_adversaries
    }
    if isinstance(additional_canonical_refs, Sequence) and not isinstance(
        additional_canonical_refs, (str, bytes)
    ):
        for raw_ref in list(additional_canonical_refs)[:MAX_ADAPTATION_ADVERSARIES]:
            ref = _safe_text(raw_ref, MAX_ADVERSARY_CHARS)
            slug = _canonical_monster_slug(ref)
            if ref and slug and slug not in seen_adversary_slugs:
                merged_adversaries.append(ref)
                seen_adversary_slugs.add(slug)

    # The separate opt-in is intentionally required even when a caller asks
    # for generation.  ``None`` is the missing-value case, not an implicit
    # approval; only the real boolean True may reach the generation seam.
    generation_enabled = allow_generation is True and generation_opt_in is True
    policy_reason = (
        "explicit_opt_in"
        if generation_enabled
        else (
            "explicit_opt_in_missing_or_invalid"
            if allow_generation is True
            else (generation_gate_reason or "disabled_by_policy")
        )
    )

    # The approved generation set is the union of explicit dossier/source
    # adversaries and canonical identities normalized from staged locations.
    # A caller-provided set can narrow neither authoritative dossier evidence
    # nor the current staging revision by accident.
    approved_generation_refs = list(merged_adversaries)
    if isinstance(approved_canonical_refs, Sequence) and not isinstance(
        approved_canonical_refs, (str, bytes)
    ):
        approved_slugs = {
            _canonical_monster_slug(value) for value in approved_generation_refs
        }
        for value in list(approved_canonical_refs)[:MAX_ADAPTATION_ADVERSARIES]:
            ref = _safe_text(value, MAX_ADVERSARY_CHARS)
            slug = _canonical_monster_slug(ref)
            if ref and slug and slug not in approved_slugs:
                approved_generation_refs.append(ref)
                approved_slugs.add(slug)

    materialization = materialize_adaptation_monsters(
        resolution_dir,
        merged_adversaries,
        seeds,
        source_module_dir=effective_source_module_dir,
        reusable_module_dirs=reusable_module_dirs,
        source_module_name=source_module_name,
        compendium_path=compendium_path,
        compendium_lookup=compendium_lookup,
        allow_generation=generation_enabled,
        monster_builder_path=monster_builder_path,
        generation_timeout_seconds=generation_timeout_seconds,
        generation_context=generation_context,
        approved_canonical_identities=approved_generation_refs,
        canonical_registry=canonical_registry,
    )

    resolution_log = materialization.get("resolution_log", [])
    resolution_diagnostics: List[Dict[str, Any]] = []
    unresolved_diagnostics: List[Dict[str, Any]] = []
    if isinstance(resolution_log, Sequence) and not isinstance(
        resolution_log, (str, bytes)
    ):
        for entry in list(resolution_log)[:MAX_RESOLUTION_DIAGNOSTICS]:
            if not isinstance(entry, Mapping):
                continue
            reference = _safe_text(entry.get("ref", ""), MAX_ADVERSARY_CHARS)
            entry_status = _safe_text(entry.get("status", ""), 32)
            reason = _safe_text(
                entry.get("reason") or "unknown_resolution_failure", 96
            )
            artifact_path = _safe_text(
                entry.get("artifact_path", ""), MAX_ARTIFACT_PATH_CHARS
            )
            resolution_entry: Dict[str, Any] = {
                "ref": reference,
                "status": entry_status,
                "source": _safe_text(entry.get("source", ""), 32),
                "reason": reason,
                "schema_sufficient": entry_status == "reused",
            }
            resolution_entry.update(
                _resolution_identity_provenance(
                    reference,
                    entry.get("canonical_slug", ""),
                    entry.get("source", ""),
                    reason,
                )
            )
            if artifact_path:
                resolution_entry["artifact_path"] = artifact_path
            source_path = _safe_text(
                entry.get("source_path", ""), MAX_ARTIFACT_PATH_CHARS
            )
            if source_path:
                resolution_entry["source_path"] = source_path
            attempts = entry.get("attempts", [])
            if isinstance(attempts, Sequence) and not isinstance(
                attempts, (str, bytes)
            ):
                resolution_entry["attempts"] = _safe_resolution_attempts(attempts)
            if entry_status == "unresolved":
                missing_fields = (
                    _missing_artifact_fields(entry.get("artifact_path"))
                    if reason == "missing_required_fields"
                    else []
                )
                if missing_fields:
                    resolution_entry["missing_required_fields"] = missing_fields
                resolution_entry["encounter_context"] = _encounter_contexts(
                    seeds, reference
                )
                unresolved_diagnostics.append(
                    {
                        "ref": reference,
                        "raw_reference": reference,
                        "canonical_identity": resolution_entry["canonical_identity"],
                        "selected_resolution_variant": resolution_entry[
                            "selected_resolution_variant"
                        ],
                        "resolution_source": resolution_entry["resolution_source"],
                        "reason": reason,
                        "schema_sufficient": False,
                        "artifact_path": artifact_path,
                        "missing_required_fields": missing_fields,
                        "encounter_context": resolution_entry["encounter_context"],
                    }
                )
            resolution_diagnostics.append(resolution_entry)

    helper_diagnostics: List[Dict[str, Any]] = []
    for entry in resolution_diagnostics:
        if entry.get("status") == "unresolved":
            helper_diagnostics.append(
                _diagnostic(
                    "unresolved_monster_reference",
                    "adversary could not be resolved to a schema-sufficient artifact",
                    adversary=entry.get("ref"),
                )
            )

    gate_diagnostics: List[Dict[str, Any]] = []
    if generation_gate_reason:
        gate_diagnostics.append(
            _diagnostic(
                "generation_staging_state_invalid",
                "canonical generation was disabled because the current staging target was not an active building revision",
            )
        )
    combined_diagnostics = (diagnostics + gate_diagnostics + helper_diagnostics)[:MAX_DIAGNOSTICS]
    status = str(materialization.get("status") or "degraded")
    if status not in {"skipped", "pass", "degraded", "blocked"}:
        status = "degraded"

    return {
        "version": ADAPTATION_MONSTER_GUARDRAIL_VERSION,
        "report_version": ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION,
        "status": status,
        "adversaries": merged_adversaries[:MAX_ADAPTATION_ADVERSARIES],
        "adversaries_planned": len(merged_adversaries),
        "monsters_planned": int(materialization.get("monsters_planned", 0)),
        "monsters_reused": int(materialization.get("monsters_reused", 0)),
        "monsters_generated": int(materialization.get("monsters_generated", 0)),
        "monsters_unresolved": int(materialization.get("monsters_unresolved", 0)),
        "monsters_excluded": int(materialization.get("monsters_excluded", 0)),
        "encounters_planned": int(materialization.get("encounters_planned", 0)),
        "encounters_bound": int(materialization.get("encounters_bound", 0)),
        "encounters_scene_resolved": int(
            materialization.get("encounters_scene_resolved", 0)
        ),
        "encounters_unresolved": int(
            materialization.get("encounters_unresolved", 0)
        ),
        "encounters_unbound": int(materialization.get("encounters_unbound", 0)),
        "unresolved_refs": [
            _safe_text(ref, MAX_ADVERSARY_CHARS)
            for ref in list(materialization.get("unresolved_refs", []))[
                :MAX_ADAPTATION_ADVERSARIES
            ]
        ],
        "non_monster_refs": [
            _safe_text(ref, MAX_ADVERSARY_CHARS)
            for ref in list(materialization.get("non_monster_refs", []))[
                :MAX_ADAPTATION_ADVERSARIES
            ]
        ],
        "unresolved_diagnostics": unresolved_diagnostics[:MAX_DIAGNOSTICS],
        "encounter_bindings": _safe_encounter_bindings(
            materialization.get("encounter_bindings", [])
        ),
        "resolution_diagnostics": resolution_diagnostics,
        "diagnostics": combined_diagnostics,
        "generation_policy": {
            "enabled": generation_enabled,
            "reason": policy_reason,
            "staging_gate": _safe_text(generation_gate_reason or "active", 96),
            "explicit_opt_in": generation_opt_in is True,
            "timeout_seconds": _generation_timeout(generation_timeout_seconds)
            if generation_enabled
            else None,
            "approved_identity_count": len(
                approved_generation_refs
            ),
        },
        "canonical_registry": {
            "version": canonical_registry.get("version")
            if isinstance(canonical_registry, Mapping)
            else None,
            "status": canonical_registry.get("status")
            if isinstance(canonical_registry, Mapping)
            else "unavailable",
            "approved_identity_count": len(
                canonical_registry.get("approved_identities", [])
            )
            if isinstance(canonical_registry, Mapping)
            else 0,
        },
    }


def run_adaptation_monster_guardrail(
    dossier: Any,
    module_dir: Optional[Union[str, Path]] = None,
    **materialization_options: Any,
) -> Dict[str, Any]:
    """Compatibility alias for callers that prefer an imperative API name."""
    return build_adaptation_monster_guardrail_report(
        dossier, module_dir, **materialization_options
    )


__all__ = [
    "ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION",
    "ADAPTATION_MONSTER_REQUIRED_FIELDS",
    "ADAPTATION_MONSTER_GUARDRAIL_VERSION",
    "ADAPTATION_SOURCE_RECONCILIATION_VERSION",
    "DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS",
    "MAX_ADAPTATION_ADVERSARIES",
    "MAX_ADAPTATION_ENCOUNTERS",
    "MAX_CANONICAL_MONSTER_VOCABULARY",
    "MAX_EXCLUDED_MONSTER_RECORDS",
    "MAX_LOCATION_MONSTER_ENTRIES",
    "MAX_MATERIALIZATION_ATTEMPTS",
    "MAX_NORMALIZED_MONSTER_RECORDS",
    "build_adaptation_monster_guardrail_report",
    "build_effective_adaptation_guardrail_input",
    "extract_adaptation_adversaries",
    "materialize_adaptation_monster_artifacts",
    "materialize_adaptation_monsters",
    "normalize_adaptation_module_monsters",
    "normalize_adaptation_location_monsters",
    "normalize_location_monsters",
    "run_adaptation_monster_guardrail",
]
