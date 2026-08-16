# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Phase 2 LLM narrative classification engine.

Architecture:
  1. Deterministic ambiguity detectors (Section 3) pre-filter authored content,
     excluding known entities/phrases/NPCs. Only ambiguous candidates are batched.
  2. ClassificationCache stores LLM results keyed by content hash (sha256),
     preventing re-calls on unchanged text. Cache lives in each module directory.
  3. Batch builders (Section 1) format ambiguous candidates into structured lists
     for LLM consumption -- one batch per domain (entity, destination, NPC).
  4. LLM classification calls (Section 2) send batches to DM_VALIDATION_MODEL
     with enum validation, fail-open to safe defaults on API failure.
  5. Python gatekeeper (Section 4) validates every LLM label against allowed enums;
     unknown labels fall back to defaults, never corrupting module JSON.
  6. Post-audit remediation proposals (Section 5 / DP4) consume residual blockers
     and propose whitelist-only transforms with Python safety validation.
  7. GUI review panel (Section 7) shows results; human accepts/rejects per-item.
  8. All LLM calls are advisory only. Python enforces the contract.
     All operations are fail-open -- the build never blocks on LLM failure.

Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from model_config import DM_VALIDATION_MODEL, ENABLE_LLM_CLASSIFICATION
from utils.ai_client_factory import (
    create_chat_client,
    get_chat_completion_params,
    get_model_config,
    handle_provider_error,
)
from utils.file_operations import safe_read_json, safe_write_json
from utils.enhanced_logger import debug, error, info, warning
from utils.module_semantic_authority import enrich_module_semantic_authority


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_classification_enabled() -> bool:
    """Return True if LLM-assisted narrative classification is active.

    Reads ``ENABLE_LLM_CLASSIFICATION`` from ``model_config``.
    Fail-open: any import or attribute error returns False.
    """
    try:
        return bool(ENABLE_LLM_CLASSIFICATION)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Classification cache
# ---------------------------------------------------------------------------

class ClassificationCache:
    """Content-hash-keyed cache for LLM classification results.

    One cache file per module directory.
    Keyed by ``sha256(text).hexdigest()`` within each classification domain.
    Fail-open: missing, malformed, or unwritable cache degrades gracefully.
    """

    def __init__(self, module_slug: str, module_dir: Optional[str] = None) -> None:
        self.slug: str = module_slug
        self.module_dir: Path
        if module_dir is not None:
            self.module_dir = Path(module_dir)
        else:
            self.module_dir = Path("modules") / module_slug

    def _cache_path(self) -> Path:
        return self.module_dir / "llm_classification_cache.json"

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, domain: str, text: str) -> Optional[str]:
        """Return cached label for ``text`` in ``domain``, or None."""
        text_hash = self._compute_hash(text)
        try:
            data = safe_read_json(str(self._cache_path()))
            if isinstance(data, dict):
                domain_data = data.get(domain, {})
                if isinstance(domain_data, dict):
                    return domain_data.get(text_hash)
            return None
        except Exception:
            return None

    def set(self, domain: str, text: str, label: str) -> None:
        """Store ``label`` for ``text`` in ``domain`` and persist atomically."""
        text_hash = self._compute_hash(text)
        try:
            cache_path = self._cache_path()
            data: Dict[str, Any] = {}
            if cache_path.exists():
                try:
                    existing = safe_read_json(str(cache_path))
                    if isinstance(existing, dict):
                        data = existing
                except Exception:
                    pass
            if domain not in data or not isinstance(data.get(domain), dict):
                data[domain] = {}
            data[domain][text_hash] = label
            safe_write_json(str(cache_path), data)
        except Exception as exc:
            warning(
                f"LLM classification cache write failed for {self.slug}/{domain}: {exc}",
                category="llm_classification",
            )


# ---------------------------------------------------------------------------
# Batch builders (Section 1)
# ---------------------------------------------------------------------------

def build_entity_classification_batch(
    entities: List[Dict[str, str]],
    area_contexts: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Format ambiguous entity mentions into an LLM classification batch.

    Each entry in *entities* should have ``name``, ``area``, and ``sentence`` keys.
    Returns a list of ``{entity_name, area_id, context}`` dicts, or ``[]`` if empty.
    """
    if not entities:
        return []
    batch: List[Dict[str, str]] = []
    for ent in entities:
        batch.append({
            "entity_name": ent.get("name", "unknown"),
            "area_id": ent.get("area", "unknown"),
            "context": ent.get("sentence", ""),
        })
    return batch


def build_destination_classification_batch(
    phrases: List[Dict[str, str]],
    area_contexts: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Format ambiguous destination phrases into an LLM classification batch.

    Each entry in *phrases* should have ``phrase``, ``area``, and ``context`` keys.
    Returns a list of ``{phrase, area_id, context}`` dicts, or ``[]`` if empty.
    """
    if not phrases:
        return []
    batch: List[Dict[str, str]] = []
    for phr in phrases:
        batch.append({
            "phrase": phr.get("phrase", "unknown"),
            "area_id": phr.get("area", "unknown"),
            "context": phr.get("context", ""),
        })
    return batch


def build_npc_visibility_batch(
    npcs: List[Dict[str, str]],
    area_contexts: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Format ambiguous NPC mentions into an LLM classification batch.

    Each entry in *npcs* should have ``npc_name``, ``area``, and ``context`` keys.
    Returns a list of ``{npc_name, area_id, context}`` dicts, or ``[]`` if empty.
    """
    if not npcs:
        return []
    batch: List[Dict[str, str]] = []
    for npc in npcs:
        batch.append({
            "npc_name": npc.get("npc_name", "unknown"),
            "area_id": npc.get("area", "unknown"),
            "context": npc.get("context", ""),
        })
    return batch


# ---------------------------------------------------------------------------
# Section 2: LLM classification calls (DP1-3)
# ---------------------------------------------------------------------------


def _call_llm_with_fallback(
    system_prompt: str,
    user_prompt: str,
    response_format: str = "json_object",
    stage: str = "toolkit_classification",
    error_sink: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        client = create_chat_client()
        config = get_model_config("dm_validation", DM_VALIDATION_MODEL)
        response = client.chat.completions.create(
            **get_chat_completion_params(
                "dm_validation",
                DM_VALIDATION_MODEL,
                temperature_override=config.get("temperature", 0.2),
            ),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": response_format},
        )
        content = response.choices[0].message.content
        if content:
            return json.loads(content)
        return None
    except Exception as exc:
        error_result = handle_provider_error(exc, stage)
        diagnostic = {
            "status": "degraded",
            "stage": stage,
            "error_type": type(exc).__name__,
            "retryable": bool(error_result.get("should_fallback", False)),
            "fallback": "classification_defaults_or_empty_proposals",
        }
        if isinstance(error_sink, list):
            error_sink.append(diagnostic)
        warning(
            f"LLM classification call failed stage={stage}: {exc}",
            category="llm_classification",
        )
        return None


def _normalize_classifications(
    raw: Any,
    key_field: str,
) -> Dict[str, str]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        result: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get(key_field, "unknown")
            label = (
                item.get("label")
                or item.get("category")
                or item.get("classification")
                or ""
            )
            result[name] = label
        return result
    return {}


def _validate_classification_labels(
    raw_labels: Dict[str, str],
    allowed_enum: set,
    default_label: str,
) -> Dict[str, str]:
    validated: Dict[str, str] = {}
    for name, label in raw_labels.items():
        if label in allowed_enum:
            validated[name] = label
        else:
            warning(
                f"LLM classification label '{label}' for '{name}' "
                f"is not in allowed enum {allowed_enum}. "
                f"Falling back to '{default_label}'.",
                category="llm_classification",
            )
            validated[name] = default_label
    return validated


def _build_cache_key_text(item: Dict[str, str], key_field: str) -> str:
    return "|".join([
        item.get(key_field, ""),
        item.get("area_id", ""),
        item.get("context", ""),
    ])


def _collect_cache_hits(
    batch: List[Dict[str, str]],
    cache: Optional[ClassificationCache],
    domain: str,
    key_field: str,
) -> tuple:
    results: Dict[str, str] = {}
    remaining: List[Dict[str, str]] = []
    if cache is None:
        return results, batch
    for item in batch:
        cache_text = _build_cache_key_text(item, key_field)
        cached_label = cache.get(domain, cache_text)
        if cached_label is not None:
            results[item.get(key_field, "unknown")] = cached_label
        else:
            remaining.append(item)
    return results, remaining


def _write_cache_hits(
    classifications: Dict[str, str],
    batch: List[Dict[str, str]],
    cache: Optional[ClassificationCache],
    domain: str,
    key_field: str,
) -> None:
    if cache is None:
        return
    for item in batch:
        name = item.get(key_field, "")
        if name in classifications:
            cache_text = _build_cache_key_text(item, key_field)
            cache.set(domain, cache_text, classifications[name])


def call_llm_classify_entities(
    batch: List[Dict[str, str]],
    cache: Optional[ClassificationCache] = None,
    module_slug: str = "",
    error_sink: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    if not batch:
        return {}

    cached_results, remaining = _collect_cache_hits(
        batch, cache, "entity", "entity_name",
    )
    if not remaining:
        return cached_results

    system_prompt = (
        "You classify ambiguous adventure entities into three categories. "
        "Return JSON: {\"classifications\": {\"entity_name\": \"label\", ...}}\n\n"
        "- combatant: a real monster that can fight\n"
        "- scene_illusion: an illusion or dressing, non-combat\n"
        "- narrator_flavor: prose-only description, not a real entity"
    )
    user_prompt = json.dumps(remaining, indent=2)

    result = _call_llm_with_fallback(
        system_prompt,
        user_prompt,
        stage="toolkit_classification.entity",
        error_sink=error_sink,
    )
    if result is None:
        info(
            "LLM entity classification degraded: API error, "
            "defaulting all to combatant",
            category="llm_classification",
        )
        defaulted = {item["entity_name"]: "combatant" for item in remaining}
        return {**cached_results, **defaulted}

    raw_classifications = _normalize_classifications(
        result.get("classifications", {}), "entity_name",
    )
    validated = _validate_classification_labels(
        raw_classifications,
        allowed_enum={"combatant", "scene_illusion", "narrator_flavor"},
        default_label="narrator_flavor",
    )
    _write_cache_hits(validated, remaining, cache, "entity", "entity_name")
    return {**cached_results, **validated}


def call_llm_classify_destinations(
    batch: List[Dict[str, str]],
    cache: Optional[ClassificationCache] = None,
    module_slug: str = "",
    error_sink: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    if not batch:
        return {}

    cached_results, remaining = _collect_cache_hits(
        batch, cache, "destination", "phrase",
    )
    if not remaining:
        return cached_results

    system_prompt = (
        "You classify ambiguous destination phrases from adventure text. "
        "Return JSON: {\"classifications\": {\"phrase\": \"label\", ...}}\n\n"
        "- canonical_alias: a real place name that should go in the travel "
        "map\n"
        "- quest_objective: a plot goal, not a travel destination\n"
        "- evocative_prose: atmospheric language, not a real place"
    )
    user_prompt = json.dumps(remaining, indent=2)

    result = _call_llm_with_fallback(
        system_prompt,
        user_prompt,
        stage="toolkit_classification.destination",
        error_sink=error_sink,
    )
    if result is None:
        info(
            "LLM destination classification degraded: API error, "
            "defaulting all to canonical_alias",
            category="llm_classification",
        )
        defaulted = {item["phrase"]: "canonical_alias" for item in remaining}
        return {**cached_results, **defaulted}

    raw_classifications = _normalize_classifications(
        result.get("classifications", {}), "phrase",
    )
    validated = _validate_classification_labels(
        raw_classifications,
        allowed_enum={"canonical_alias", "quest_objective", "evocative_prose"},
        default_label="evocative_prose",
    )
    _write_cache_hits(validated, remaining, cache, "destination", "phrase")
    return {**cached_results, **validated}


def call_llm_classify_npc_visibility(
    batch: List[Dict[str, str]],
    cache: Optional[ClassificationCache] = None,
    module_slug: str = "",
    error_sink: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    if not batch:
        return {}

    cached_results, remaining = _collect_cache_hits(
        batch, cache, "npc_visibility", "npc_name",
    )
    if not remaining:
        return cached_results

    system_prompt = (
        "You classify ambiguous NPC mentions from adventure text. "
        "Return JSON: {\"classifications\": {\"npc_name\": \"label\", ...}}\n\n"
        "- visible: the NPC is physically present and can be seen\n"
        "- hidden_reveal: the NPC is hidden but can be revealed\n"
        "- lore_only: the NPC is mentioned in backstory or legend, "
        "not physically present"
    )
    user_prompt = json.dumps(remaining, indent=2)

    result = _call_llm_with_fallback(
        system_prompt,
        user_prompt,
        stage="toolkit_classification.npc_visibility",
        error_sink=error_sink,
    )
    if result is None:
        info(
            "LLM NPC visibility classification degraded: API error, "
            "defaulting all to visible",
            category="llm_classification",
        )
        defaulted = {item["npc_name"]: "visible" for item in remaining}
        return {**cached_results, **defaulted}

    raw_classifications = _normalize_classifications(
        result.get("classifications", {}), "npc_name",
    )
    validated = _validate_classification_labels(
        raw_classifications,
        allowed_enum={"visible", "hidden_reveal", "lore_only"},
        default_label="lore_only",
    )
    _write_cache_hits(validated, remaining, cache, "npc_visibility", "npc_name")
    return {**cached_results, **validated}


# ---------------------------------------------------------------------------
# Section 3: Ambiguity detection (deterministic pre-filter)
# ---------------------------------------------------------------------------


_COMPENDIUM_PATH = Path("data/bestiary/monster_compendium.json")
_DESTINATION_TERMINALS = frozenset({
    "tower", "shrine", "camp", "keep", "gate", "bridge", "village",
    "cavern", "hall", "sanctum", "crypt", "chamber", "ruins", "fort",
    "temple", "mine", "labyrinth", "pass", "road", "tavern", "inn",
})


# ---------------------------------------------------------------------------
# 3.1  Entity ambiguity
# ---------------------------------------------------------------------------


def _normalize_name_for_bestiary(raw: str) -> str:
    return raw.lower().strip().replace(" ", "_")


def _is_in_bestiary(name: str) -> bool:
    slug = _normalize_name_for_bestiary(name)
    try:
        data = safe_read_json(str(_COMPENDIUM_PATH))
        if isinstance(data, dict):
            monsters = data.get("monsters", {})
            if isinstance(monsters, dict) and slug in monsters:
                return True
    except Exception:
        pass
    try:
        monster_path = Path("data/bestiary") / f"{slug}.json"
        if monster_path.exists():
            return True
    except Exception:
        pass
    return False


def detect_ambiguous_entities(
    module_dir: str,
) -> List[Dict[str, str]]:
    module_path = Path(module_dir)
    areas_dir = module_path / "areas"
    if not areas_dir.is_dir():
        return []

    ambiguous: List[Dict[str, str]] = []
    seen: set = set()

    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        area_id = area.get("areaId", area_path.stem)
        for loc in area.get("locations", []):
            loc_id = loc.get("locationId", "?")
            for mon in loc.get("monsters", []):
                if isinstance(mon, str):
                    name = mon.strip()
                elif isinstance(mon, dict):
                    name = (mon.get("name") or "").strip()
                else:
                    continue
                if not name:
                    continue
                if not _is_in_bestiary(name):
                    dedup_key = _normalize_name_for_bestiary(name)
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        ambiguous.append({
                            "name": name,
                            "area": area_id,
                            "sentence": (
                                loc.get("description", "")
                                or loc.get("dmInstructions", "")
                                or ""
                            )[:300],
                        })
    return ambiguous


# ---------------------------------------------------------------------------
# 3.2  Destination ambiguity
# ---------------------------------------------------------------------------


def detect_ambiguous_destinations(
    module_dir: str,
) -> List[Dict[str, str]]:
    module_path = Path(module_dir)
    areas_dir = module_path / "areas"

    known_ids: set = set()
    known_aliases: set = set()
    ctx_path = module_path / "module_context.json"
    try:
        ctx = safe_read_json(str(ctx_path))
        if isinstance(ctx, dict):
            sem = ctx.get("semantic_authority", {}) or {}
            loc_aliases = sem.get("location_aliases", {}) or {}
            if isinstance(loc_aliases, dict):
                for phrase, info in loc_aliases.items():
                    if isinstance(info, dict) and info.get("status") == "resolved":
                        known_aliases.add(phrase.lower().strip())
            dst_phrases = sem.get("destination_phrases", {}) or {}
            if isinstance(dst_phrases, dict):
                for phrase, info in dst_phrases.items():
                    if isinstance(info, dict) and info.get("status") == "resolved":
                        known_aliases.add(phrase.lower().strip())
    except Exception:
        pass

    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        for loc in area.get("locations", []):
            if not isinstance(loc, dict):
                continue
            known_ids.add(loc.get("locationId", ""))
            for alias in loc.get("aliases", []):
                if isinstance(alias, str):
                    known_aliases.add(alias.lower().strip())

    ambiguous: List[Dict[str, str]] = []
    seen: set = set()

    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        area_id = area.get("areaId", area_path.stem)
        corpus = ""
        for loc in area.get("locations", []):
            if isinstance(loc, dict):
                for field in ("description", "dmInstructions", "name"):
                    val = loc.get(field, "")
                    if isinstance(val, str):
                        corpus += val + " "
        tokens = corpus.lower().split()
        for i, token in enumerate(tokens):
            clean = token.strip(".,!?;:'\"()[]{}")
            if clean in _DESTINATION_TERMINALS and i > 0:
                phrase = tokens[i - 1] + " " + clean
                phrase_clean = phrase.strip(".,!?;:'\"()[]{}")
                if phrase_clean not in known_aliases and phrase_clean not in known_ids:
                    dedup_key = phrase_clean
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        ambiguous.append({
                            "phrase": phrase,
                            "area": area_id,
                            "context": corpus[:300],
                        })
    return ambiguous


# ---------------------------------------------------------------------------
# 3.3  NPC visibility ambiguity
# ---------------------------------------------------------------------------


def detect_ambiguous_npc_visibility(
    module_dir: str,
) -> List[Dict[str, str]]:
    module_path = Path(module_dir)
    areas_dir = module_path / "areas"

    visible_npcs: set = set()
    ctx_path = module_path / "module_context.json"
    try:
        ctx = safe_read_json(str(ctx_path))
        if isinstance(ctx, dict):
            sem = ctx.get("semantic_authority", {}) or {}
            nsc = sem.get("npc_scene_authority", {}) or {}
            if isinstance(nsc, dict):
                for name, info in nsc.items():
                    if isinstance(info, dict):
                        if info.get("visible_location_ids"):
                            visible_npcs.add(info.get("name_slug", "") or name.lower().strip())
                        if info.get("reveal_bindings") or info.get("reveal_authority"):
                            visible_npcs.add(info.get("name_slug", "") or name.lower().strip())
    except Exception:
        pass

    ambiguous: List[Dict[str, str]] = []
    seen: set = set()

    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        area_id = area.get("areaId", area_path.stem)
        for loc in area.get("locations", []):
            if not isinstance(loc, dict):
                continue
            for npc in loc.get("npcs", []):
                if not isinstance(npc, dict):
                    continue
                name = (npc.get("name") or "").strip()
                if not name:
                    continue
                slug = name.lower().strip().replace(" ", "_")
                if slug in visible_npcs:
                    continue
                dedup_key = slug
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    ambiguous.append({
                        "npc_name": name,
                        "area": area_id,
                        "context": (
                            npc.get("description", "")
                            or loc.get("description", "")
                            or ""
                        )[:300],
                    })
    return ambiguous


# ---------------------------------------------------------------------------
# 3.4  Orchestrator
# ---------------------------------------------------------------------------


def run_llm_classification_pass(
    module_dir: str,
    module_slug: str = "",
) -> Dict[str, Any]:
    slug = module_slug or Path(module_dir).name

    if not is_classification_enabled():
        return {"status": "bypassed", "reason": "feature_flag_disabled"}

    cache = ClassificationCache(slug, module_dir=module_dir)

    result: Dict[str, Any] = {
        "status": "success",
        "classifications": {},
        "summaries": {},
        "errors": [],
        "provider_errors": [],
    }

    def _classify_domain(
        detector_fn,
        batch_builder_fn,
        classifier_fn,
        domain_name: str,
    ) -> Dict[str, Any]:
        domain_result: Dict[str, Any] = {
            "candidates": 0,
            "cache_hits": 0,
            "llm_classified": 0,
            "labels": {},
        }
        try:
            raw = detector_fn(module_dir)
        except Exception as exc:
            info(
                f"Ambiguity detection failed for {domain_name}: {exc}",
                category="llm_classification",
            )
            result["errors"].append(f"detection_{domain_name}_failed")
            return domain_result

        domain_result["candidates"] = len(raw)
        if not raw:
            return domain_result

        try:
            batch = batch_builder_fn(raw)
        except Exception as exc:
            info(
                f"Batch builder failed for {domain_name}: {exc}",
                category="llm_classification",
            )
            result["errors"].append(f"batch_{domain_name}_failed")
            return domain_result

        try:
            labels = classifier_fn(
                batch,
                cache=cache,
                module_slug=slug,
                error_sink=result["provider_errors"],
            )
        except Exception as exc:
            info(
                f"Classification call failed for {domain_name}: {exc}",
                category="llm_classification",
            )
            result["errors"].append(f"classify_{domain_name}_failed")
            return domain_result

        domain_result["labels"] = labels
        domain_result["llm_classified"] = len(labels)
        result["classifications"][domain_name] = labels
        return domain_result

    result["summaries"]["entity"] = _classify_domain(
        detect_ambiguous_entities,
        build_entity_classification_batch,
        call_llm_classify_entities,
        "entity",
    )
    result["summaries"]["destination"] = _classify_domain(
        detect_ambiguous_destinations,
        build_destination_classification_batch,
        call_llm_classify_destinations,
        "destination",
    )
    result["summaries"]["npc_visibility"] = _classify_domain(
        detect_ambiguous_npc_visibility,
        build_npc_visibility_batch,
        call_llm_classify_npc_visibility,
        "npc_visibility",
    )

    if result["errors"] or result["provider_errors"]:
        result["status"] = "degraded"
    return result


# ---------------------------------------------------------------------------
# Section 4: Classification apply (Python gatekeeper)
# ---------------------------------------------------------------------------


def _normalize_entity_name(raw: str) -> str:
    return raw.lower().strip()


def _extract_name_from_monster(monster: Any) -> Optional[str]:
    if isinstance(monster, dict):
        return monster.get("name")
    if isinstance(monster, str):
        parts = monster.strip().split(None, 1)
        if len(parts) == 2:
            try:
                int(parts[0])
                return parts[1]
            except ValueError:
                return parts[1] if len(parts) >= 1 else parts[0]
        return parts[0] if parts else None
    return None


def apply_entity_classifications(
    module_dir: str,
    classifications: Dict[str, str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "success", "applied": 0, "details": []}
    if not classifications:
        return result
    areas_dir = Path(module_dir) / "areas"
    if not areas_dir.is_dir():
        return result
    ts = datetime.utcnow().isoformat()
    norm_classifications: Dict[str, str] = {
        _normalize_entity_name(k): v for k, v in classifications.items()
    }
    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        area_id = area.get("areaId", area_path.stem)
        changed = False
        for loc in area.get("locations", []):
            if not isinstance(loc, dict):
                continue
            monsters = loc.get("monsters")
            if not isinstance(monsters, list):
                continue
            new_monsters: List[Any] = []
            removed: List[str] = []
            for monster in monsters:
                name = _extract_name_from_monster(monster)
                if not name:
                    new_monsters.append(monster)
                    continue
                norm_name = _normalize_entity_name(name)
                label = norm_classifications.get(norm_name)
                if label == "narrator_flavor":
                    removed.append(name)
                    annot: Dict[str, Any] = {
                        "name": name,
                        "original_area": area_id,
                        "applied_at": ts,
                    }
                    existing_meta = loc.get("_llm_metadata")
                    if isinstance(existing_meta, dict):
                        existing_meta.setdefault("reclassified_entities", [])
                        if not any(
                            e.get("name") == name
                            for e in existing_meta["reclassified_entities"]
                        ):
                            existing_meta["reclassified_entities"].append(annot)
                        loc["_llm_metadata"] = existing_meta
                    else:
                        loc["_llm_metadata"] = {"reclassified_entities": [annot]}
                    changed = True
                elif label == "scene_illusion":
                    if isinstance(monster, dict):
                        monster["sceneEntity"] = {
                            "combatValidity": "scene_only",
                            "manifestation": "incorporeal",
                            "violencePolicy": "incorporeal_no_effect",
                        }
                        monster["_llm_metadata"] = {
                            "provenance": "llm_classification",
                            "classified_by": DM_VALIDATION_MODEL,
                            "classified_at": ts,
                            "label": "scene_illusion",
                        }
                        changed = True
                    new_monsters.append(monster)
                else:
                    new_monsters.append(monster)
            if removed:
                loc["monsters"] = new_monsters
                result["details"].append(
                    f"area={area_id} removed={removed}"
                )
        if changed:
            try:
                safe_write_json(str(area_path), area)
                result["applied"] += 1
            except Exception as exc:
                warning(
                    f"Entity classification write failed for {area_path}: {exc}",
                    category="llm_classification",
                )
    return result


def _find_target_location(
    area: Dict[str, Any],
    phrase: str,
) -> Optional[str]:
    phrase_lower = phrase.lower().strip()
    for loc in area.get("locations", []):
        if not isinstance(loc, dict):
            continue
        for candidate in [loc.get("name", ""), loc.get("description", "")]:
            if isinstance(candidate, str) and phrase_lower in candidate.lower():
                return loc.get("locationId")
        for alias in loc.get("aliases", []):
            if isinstance(alias, str) and phrase_lower == alias.lower().strip():
                return loc.get("locationId")
    return None


def apply_destination_classifications(
    module_dir: str,
    classifications: Dict[str, str],
) -> Dict[str, str]:
    result: Dict[str, str] = {
        "status": "success", "applied": "0", "aliases_added": "[]",
    }
    if not classifications:
        return result
    areas_dir = Path(module_dir) / "areas"
    if not areas_dir.is_dir():
        return result
    ts = datetime.utcnow().isoformat()
    canon_phrases: Dict[str, str] = {
        k.lower().strip(): v for k, v in classifications.items()
        if v == "canonical_alias"
    }
    if not canon_phrases:
        return result
    added: List[str] = []
    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        changed = False
        for loc in area.get("locations", []):
            if not isinstance(loc, dict):
                continue
            for phrase in canon_phrases:
                target_id = _find_target_location(area, phrase)
                if target_id and target_id == loc.get("locationId"):
                    existing = loc.get("aliases")
                    if not isinstance(existing, list):
                        loc["aliases"] = []
                        existing = loc["aliases"]
                    norm_existing = {a.lower().strip() for a in existing if isinstance(a, str)}
                    if phrase.lower().strip() not in norm_existing:
                        existing.append(phrase)
                        changed = True
                        added.append(f"{phrase} -> {area_path.name}#{target_id}")
        if changed:
            try:
                safe_write_json(str(area_path), area)
            except Exception as exc:
                warning(
                    f"Destination classification write failed for {area_path}: {exc}",
                    category="llm_classification",
                )
    try:
        enrich_module_semantic_authority(
            Path(module_dir).name, {}, {}, module_dir,
        )
    except Exception as exc:
        info(
            f"Semantic authority regeneration failed: {exc}",
            category="llm_classification",
        )
    result["applied"] = str(len(added))
    result["aliases_added"] = json.dumps(added)
    return result


def apply_npc_visibility_classifications(
    module_dir: str,
    classifications: Dict[str, str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "success", "applied": 0, "details": []}
    if not classifications:
        return result
    areas_dir = Path(module_dir) / "areas"
    if not areas_dir.is_dir():
        return result
    context_path = Path(module_dir) / "module_context.json"
    ts = datetime.utcnow().isoformat()
    try:
        context = safe_read_json(str(context_path))
    except Exception:
        context = {}
    if not isinstance(context, dict):
        context = {}
    sem = context.setdefault("semantic_authority", {})
    nsc = sem.setdefault("npc_scene_authority", {})
    norm_classifications: Dict[str, str] = {
        k.lower().strip().replace(" ", "_"): v
        for k, v in classifications.items()
    }
    context_changed = False
    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        area_id = area.get("areaId", area_path.stem)
        area_changed = False
        for loc in area.get("locations", []):
            if not isinstance(loc, dict):
                continue
            for npc in loc.get("npcs", []):
                if not isinstance(npc, dict):
                    continue
                name = (npc.get("name") or "").strip()
                if not name:
                    continue
                slug = name.lower().strip().replace(" ", "_")
                label = norm_classifications.get(slug)
                if label is None:
                    continue
                loc_id = loc.get("locationId", "")
                entry = nsc.get(name)
                if not isinstance(entry, dict):
                    entry = {
                        "name_slug": slug,
                        "visible_location_ids": [],
                        "reveal_bindings": [],
                        "sources": [],
                        "authored_mentions_count": 0,
                        "authored_mention_sources": [],
                    }
                    nsc[name] = entry
                if label == "visible":
                    if loc_id and loc_id not in entry.get("visible_location_ids", []):
                        entry.setdefault("visible_location_ids", []).append(loc_id)
                        context_changed = True
                        area_changed = True
                elif label == "hidden_reveal":
                    binding = {"location_id": loc_id, "source": "llm_classification",
                               "reason": "llm_classified"}
                    existing_bindings = entry.setdefault("reveal_bindings", [])
                    if binding not in existing_bindings:
                        existing_bindings.append(binding)
                        context_changed = True
                        area_changed = True
        if area_changed:
            result["applied"] += 1
    if context_changed:
        try:
            nsc.setdefault("_llm_metadata", {})
            nsc["_llm_metadata"] = {
                "provenance": "llm_classification",
                "classified_by": DM_VALIDATION_MODEL,
                "classified_at": ts,
            }
            safe_write_json(str(context_path), context)
        except Exception as exc:
            warning(
                f"NPC visibility context write failed: {exc}",
                category="llm_classification",
            )
    result["status"] = "success"
    return result


def persist_classification_metadata(
    module_dir: str,
    entity_classifications: Dict[str, str],
    destination_classifications: Dict[str, str],
    npc_classifications: Dict[str, str],
) -> None:
    context_path = Path(module_dir) / "module_context.json"
    try:
        context = safe_read_json(str(context_path))
    except Exception:
        context = {}
    if not isinstance(context, dict):
        context = {}
    ts = datetime.utcnow().isoformat()
    context["classification_metadata"] = {
        "classified_by": DM_VALIDATION_MODEL,
        "classified_at": ts,
        "entity_count": len(entity_classifications),
        "destination_count": len(destination_classifications),
        "npc_count": len(npc_classifications),
        "provenance": "llm_classification",
        "feature_flag": "ENABLE_LLM_CLASSIFICATION",
    }
    try:
        safe_write_json(str(context_path), context)
    except Exception as exc:
        warning(
            f"Classification metadata write failed: {exc}",
            category="llm_classification",
        )


# ---------------------------------------------------------------------------
# Section 5: Remediation proposals (DP4)
# ---------------------------------------------------------------------------

_WHITELIST_TRANSFORMS: set = {
    "move_entity_to_scene_entity",
    "add_canonical_alias",
    "add_npc_visibility",
    "suppress_from_monsters",
    "suppress_from_travel_map",
    "set_npc_reveal_authority",
}


def _proposal_target_exists(
    module_dir: str,
    target: str,
    transform_type: str,
) -> bool:
    target_lower = target.lower().strip()
    area_dir = Path(module_dir) / "areas"
    if not area_dir.is_dir():
        return False

    entity_types = {"move_entity_to_scene_entity", "suppress_from_monsters"}
    dest_types = {"add_canonical_alias", "suppress_from_travel_map"}
    npc_types = {"add_npc_visibility", "set_npc_reveal_authority"}

    for area_path in sorted(area_dir.glob("*.json")):
        if area_path.stem.endswith("_BU"):
            continue
        try:
            area = safe_read_json(str(area_path))
        except Exception:
            continue
        if not isinstance(area, dict):
            continue
        for loc in area.get("locations", []):
            if not isinstance(loc, dict):
                continue
            if transform_type in entity_types:
                for monster in loc.get("monsters", []):
                    if isinstance(monster, dict):
                        name = monster.get("name", "").lower().strip()
                    elif isinstance(monster, str):
                        name = monster.lower().strip()
                    else:
                        continue
                    if target_lower in name:
                        return True
            if transform_type in dest_types:
                for field in ("name", "description", "aliases"):
                    text = loc.get(field, "")
                    if isinstance(text, str) and target_lower in text.lower():
                        return True
                if target_lower in loc.get("locationId", "").lower():
                    return True
            if transform_type in npc_types:
                for npc in loc.get("npcs", []):
                    if isinstance(npc, dict):
                        npc_name = npc.get("name", "").lower().strip()
                        if target_lower in npc_name or npc_name in target_lower:
                            return True
    return False


def build_remediation_proposal_batch(
    module_dir: str,
    blocker_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    blocker_classes = blocker_report.get("blocker_classes", [])
    if not blocker_classes:
        return []

    batch_item: Dict[str, Any] = {
        "blocker_classes": sorted(blocker_classes),
        "entity_classifications": blocker_report.get("entity_classifications", {}),
        "destination_classifications": blocker_report.get(
            "destination_classifications", {},
        ),
        "npc_classifications": blocker_report.get("npc_classifications", {}),
        "available_transforms": sorted(_WHITELIST_TRANSFORMS),
    }
    return [batch_item]


def call_llm_remediation_proposals(
    batch: List[Dict[str, Any]],
    error_sink: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    if not batch:
        return []

    system_prompt = (
        "You propose concrete fixes for module publishability blockers. "
        "Each proposal MUST use one of the allowed transform types below. "
        "Return JSON with a 'proposals' array.\n\n"
        "Allowed transform types:\n"
        "- move_entity_to_scene_entity: convert a monster entry into "
        "scene-only entity metadata\n"
        "- add_canonical_alias: register a destination phrase as an "
        "area alias for travel authority\n"
        "- add_npc_visibility: mark an NPC as visible (present and "
        "can be found)\n"
        "- suppress_from_monsters: remove a flavor entity from the "
        "monsters catalog\n"
        "- suppress_from_travel_map: exclude an evocative phrase "
        "from travel destination maps\n"
        "- set_npc_reveal_authority: mark an NPC as hidden-but-revealable "
        "with reveal metadata\n\n"
        "Format each proposal as:\n"
        "{\n"
        '  "transform_type": "<allowed type>",\n'
        '  "target": "<entity/phrase/NPC name>",\n'
        '  "description": "<brief description of what changes>",\n'
        '  "rationale": "<why this fixes the blocker>"\n'
        "}"
    )
    user_prompt = json.dumps(batch, indent=2)

    result = _call_llm_with_fallback(
        system_prompt,
        user_prompt,
        stage="toolkit_classification.remediation",
        error_sink=error_sink,
    )
    if result is None:
        info(
            "LLM remediation proposals degraded: API error, "
            "returning empty proposals",
            category="llm_classification",
        )
        return []

    proposals = result.get("proposals", [])
    if isinstance(proposals, list):
        validated_proposals: List[Dict[str, str]] = []
        for p in proposals:
            if isinstance(p, dict) and p.get("transform_type") and p.get("target"):
                validated_proposals.append(p)
        return validated_proposals
    return []


def validate_remediation_proposals(
    module_dir: str,
    proposals: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    if not proposals:
        return []

    validated: List[Dict[str, str]] = []
    for proposal in proposals:
        tt = proposal.get("transform_type", "")
        target = proposal.get("target", "")

        p: Dict[str, str] = dict(proposal)

        if tt not in _WHITELIST_TRANSFORMS:
            p["safety"] = f"warning:unwhitelisted_transform:{tt}"
            warning(
                f"Rejected unwhitelisted transform type '{tt}'",
                category="llm_classification",
            )
            validated.append(p)
            continue

        if not target:
            p["safety"] = "fail:target_missing"
            validated.append(p)
            continue

        if not _proposal_target_exists(module_dir, target, tt):
            p["safety"] = "fail:target_missing"
            validated.append(p)
            continue

        p["safety"] = "pass"
        validated.append(p)

    return validated


def apply_accepted_proposals(
    module_dir: str,
    accepted_proposals: List[Dict[str, str]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "applied": 0,
        "failed": 0,
        "transforms": [],
    }

    for proposal in accepted_proposals:
        tt = proposal.get("transform_type", "")
        target = proposal.get("target", "")
        safety = proposal.get("safety", "pass")

        if not target or not tt:
            result["failed"] += 1
            continue

        if safety not in ("pass",):
            result["failed"] += 1
            continue

        try:
            if tt in ("move_entity_to_scene_entity", "suppress_from_monsters"):
                label = "scene_illusion" if tt == "move_entity_to_scene_entity" else "narrator_flavor"
                apply_result = apply_entity_classifications(
                    module_dir, {target: label},
                )
                if apply_result.get("applied", 0) > 0:
                    result["applied"] += 1
                    result["transforms"].append({
                        "transform_type": tt, "target": target,
                        "status": "applied",
                    })
                else:
                    result["failed"] += 1
                    result["transforms"].append({
                        "transform_type": tt, "target": target,
                        "status": "no_match",
                    })

            elif tt == "add_canonical_alias":
                apply_result = apply_destination_classifications(
                    module_dir, {target: "canonical_alias"},
                )
                if apply_result.get("applied", 0) > 0:
                    result["applied"] += 1
                    result["transforms"].append({
                        "transform_type": tt, "target": target,
                        "status": "applied",
                    })
                else:
                    result["failed"] += 1
                    result["transforms"].append({
                        "transform_type": tt, "target": target,
                        "status": "no_match",
                    })

            elif tt == "suppress_from_travel_map":
                apply_result = apply_destination_classifications(
                    module_dir, {target: "evocative_prose"},
                )
                result["applied"] += 1
                result["transforms"].append({
                    "transform_type": tt, "target": target,
                    "status": "applied",
                })

            elif tt in ("add_npc_visibility", "set_npc_reveal_authority"):
                label = "visible" if tt == "add_npc_visibility" else "hidden_reveal"
                apply_result = apply_npc_visibility_classifications(
                    module_dir, {target: label},
                )
                if apply_result.get("applied", 0) > 0:
                    result["applied"] += 1
                    result["transforms"].append({
                        "transform_type": tt, "target": target,
                        "status": "applied",
                    })
                else:
                    result["failed"] += 1
                    result["transforms"].append({
                        "transform_type": tt, "target": target,
                        "status": "no_match",
                    })

            else:
                result["failed"] += 1
                result["transforms"].append({
                    "transform_type": tt, "target": target,
                    "status": "unsupported",
                })

        except Exception as exc:
            warning(
                f"Remediation proposal apply failed for {tt}:{target}: {exc}",
                category="llm_classification",
            )
            result["failed"] += 1
            result["transforms"].append({
                "transform_type": tt, "target": target,
                "status": "error",
            })

    result["status"] = "success"
    return result
