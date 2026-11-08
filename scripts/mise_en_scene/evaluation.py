# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free R8 proposal, leakage review, assignment, and hash binding."""

from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import projections


_CONDITIONS = ("A", "B", "C", "D")
_PARTY_SHAPES = ("P1", "P4")
_TOKENIZER_ID = (
    "mise-en-scene-lexical-fingerprint-v1; top 32 terms, stopwords and "
    "layout vocabulary v1"
)
_EXPECTED_CATALOG_SHA256 = (
    "7defa824776c8a08dd5c2669148563680d08bd466bfb45483825703bb1634165"
)
_EXPECTED_M1_MANIFEST_SHA256 = (
    "b3a9f405a390028cc173420a1d8df0f5b74173eaf84bcf0120b215b35ee83e77"
)
_EXPECTED_OWNER_FEEDBACK_SHA256 = (
    "721373d9c99c69dfedb844d8671ad6cb5c106265ce64b14d928dd6d64146c2d6"
)
_EXPECTED_M1_RECORD_IDS = (
    "m1:fixture-interior_tavern-MPV2_LOC_TAVERN-start-1b2c19ae8c47",
    "m1:fixture-landscape_village-MPV2_LOC_VILLAGE_GREEN-start-5035a149fc68",
    "m1:fixture-transition_tower_approach-MPV2_LOC_TOWER_APPROACH-start-45f89e279035",
    "m1:fixture-combat_stage_tavern_zones-MPV2_LOC_TAVERN-P1-3eef50e1733d",
    "m1:fixture-combat_stage_tavern_zones-MPV2_LOC_TAVERN-P4-147cc61822ee",
    "m1:d1-Keep_of_Doom-AA01-D1-review-start-e1f0b1cdde26",
    "m1:d1-Keep_of_Doom-AL01-D1-review-start-22fddc6eb767",
    "m1:d1-The_Thornwood_Watch-NC01-D1-review-start-c006660c84d4",
    "m1:d1-The_Thornwood_Watch-NC04-D1-review-start-cc9f57501237",
    "m1:d1-The_Thornwood_Watch-NC05-D1-review-start-40c08ae46c2b",
    "m1:d1-The_Pumpkin_Kings_Curse-AD01-D1-review-start-d7a580f44c4e",
    "m1:d1-The_Pumpkin_Kings_Curse-AB01-D1-review-start-9a3f3a19cebe",
    "m1:d1-The_Pumpkin_Kings_Curse-V01-D1-review-start-5fa169079dd9",
    "m1:d1-The_Pumpkin_Kings_Curse-AB02-D1-review-start-fc5bfc09cc82",
    "m1:d1-The_Pumpkin_Kings_Curse-V02-D1-review-start-37243b1f8a0c",
    "m1:d1-The_Pumpkin_Kings_Curse-AB03-D1-review-start-122b55e14ca2",
)
_EXPECTED_OWNER_LINEAGE = {
    "owner:A": "m1:d1-Keep_of_Doom-AL01-D1-review-start-22fddc6eb767",
    "owner:B": "m1:d1-The_Pumpkin_Kings_Curse-AB01-D1-review-start-9a3f3a19cebe",
    "owner:C": "m1:d1-The_Pumpkin_Kings_Curse-AB02-D1-review-start-fc5bfc09cc82",
    "owner:D": "m1:d1-The_Pumpkin_Kings_Curse-AB03-D1-review-start-122b55e14ca2",
    "owner:E": "m1:d1-The_Pumpkin_Kings_Curse-V01-D1-review-start-5fa169079dd9",
    "owner:F": "m1:d1-The_Pumpkin_Kings_Curse-V02-D1-review-start-37243b1f8a0c",
    "owner:G": "m1:d1-The_Thornwood_Watch-NC01-D1-review-start-c006660c84d4",
    "owner:H": "m1:d1-The_Thornwood_Watch-NC04-D1-review-start-cc9f57501237",
    "owner:I": "m1:d1-The_Thornwood_Watch-NC05-D1-review-start-40c08ae46c2b",
}
_EXPECTED_OWNER_RECORD_IDS = tuple("owner:" + letter for letter in "ABCDEFGHI")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SCENE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:scene:[a-z0-9][a-z0-9_-]{0,63}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WORD_RE = re.compile(r"[a-z][a-z0-9]{0,31}")
_MAX_SCENES = 6
_MAX_KNOWN_RECORDS = 25
_MAX_TEXT_CHARS = 32_768
_MAX_SOURCE_REF_CHARS = 512
_MAX_IDENTITY_CHARS = 256
_MAX_LINEAGE = 32
_MAX_EXPLICIT_TOKENS = 64
_MAX_ARTIFACT_CHARS = 32_768
_MAX_MANIFEST_BYTES = 4_000_000
_TEXT_OVERLAP_MIN_SHARED = 3
_TEXT_OVERLAP_MIN_JACCARD_PPM = 200_000
_LAYOUT_OVERLAP_MIN_SHARED = 2
_LAYOUT_OVERLAP_MIN_JACCARD_PPM = 250_000
_FEATURE_OVERLAP_MIN_SHARED = 3
_FEATURE_OVERLAP_MIN_JACCARD_PPM = 250_000

_STOPWORDS = frozenset(
    "a an and are as at be been being by can could did do does for from had "
    "has have he her his how i if in into is it its may might more most must "
    "no not of on or other our out over she should so some such than that "
    "the their them there these they this those through to under up us was "
    "were what when where which who why will with would you your score scores "
    "scored rating ratings rated owner judgment judgments".split()
)
_LAYOUT_TERMS = frozenset(
    "n ne e se s sw w nw c center centred centered centre north northern "
    "northeast east eastern southeast south southern southwest west western "
    "northwest approach threshold focal boundary edge frontage adjacent inside "
    "outside between beyond behind toward towards route path grid cell cells "
    "extent position anchor space entrance exit connection left right near "
    "through across around side sides corner corners region regional doorway "
    "access gate facing face open opening start arrival return transition".split()
)


class EvaluationManifestError(ValueError):
    """Stable error for invalid proposed manifests or approval bindings."""

    def __init__(
        self, code: str, path: str = "$", details: object | None = None
    ) -> None:
        self.code = code
        self.path = path
        self.details = details
        super().__init__(code + " at " + path)


def _read_bundled_catalog() -> dict[str, Any]:
    path = Path(__file__).with_name("known_examples.json")
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("bundled known-example catalog is unreadable") from exc
    if type(value) is not dict:
        raise RuntimeError("bundled known-example catalog is not an object")
    return value


_BUNDLED_CATALOG = _read_bundled_catalog()


def _canonical_json(value: object) -> str:
    try:
        return projections.canonical_json(value)
    except projections.ProjectionError as exc:
        raise EvaluationManifestError("CANONICAL_JSON_VALUE", exc.path) from exc


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: object, path: str) -> str:
    if not _is_sha256(value):
        raise EvaluationManifestError("SHA256_REQUIRED", path)
    assert type(value) is str
    return value


def _require_record(
    value: object, expected_keys: set[str], path: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise EvaluationManifestError("OBJECT_REQUIRED", path)
    if set(value) != expected_keys:
        missing = sorted(expected_keys - set(value))
        extra = sorted(set(value) - expected_keys)
        detail = "missing=" + (missing[0] if missing else "none")
        detail += ";extra=" + (extra[0] if extra else "none")
        raise EvaluationManifestError("RECORD_FIELDS", path, detail)
    return value


def _validate_token_list(
    value: object, path: str, *, maximum: int
) -> list[str]:
    if type(value) is not list or len(value) > maximum:
        raise EvaluationManifestError("TOKEN_LIST_LIMIT", path)
    if any(type(token) is not str or not _TOKEN_RE.fullmatch(token) for token in value):
        raise EvaluationManifestError("TOKEN_INVALID", path)
    tokens = list(value)
    if tokens != sorted(set(tokens)):
        raise EvaluationManifestError("TOKEN_LIST_NOT_CANONICAL", path)
    return tokens


def _selected_text_tokens(text: str) -> list[str]:
    counts = Counter(
        token
        for token in _WORD_RE.findall(text.lower())
        if token not in _STOPWORDS and not token.isdigit()
    )
    return sorted(counts, key=lambda token: (-counts[token], token))[:32]


def _fingerprint_tokens(tokens: list[str]) -> dict[str, Any]:
    ordered = sorted(set(tokens))
    layout = sorted(set(ordered) & _LAYOUT_TERMS)
    features = sorted(set(ordered) - _LAYOUT_TERMS)
    return {
        "text_tokens": ordered,
        "text_fingerprint_sha256": _hash_json(ordered),
        "layout_tokens": layout,
        "layout_fingerprint_sha256": _hash_json(layout),
        "feature_tokens": features,
        "feature_fingerprint_sha256": _hash_json(features),
    }


def fingerprint_source_text(source_text: object) -> dict[str, Any]:
    """Return bounded, deterministic lexical/layout/feature fingerprints."""

    if (
        type(source_text) is not str
        or not source_text.strip()
        or len(source_text) > _MAX_TEXT_CHARS
    ):
        raise EvaluationManifestError("SOURCE_TEXT", "$.source_text")
    try:
        source_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EvaluationManifestError("SOURCE_TEXT_ENCODING", "$.source_text") from exc
    return _fingerprint_tokens(_selected_text_tokens(source_text))


def load_known_examples() -> dict[str, Any]:
    """Return a detached copy of the bundled development-only leakage catalog."""

    return copy.deepcopy(_BUNDLED_CATALOG)


def validate_known_examples(catalog: object) -> str:
    """Validate the complete pinned 16+9 catalog and return its canonical hash."""

    expected_top = {"schema_version", "catalog_kind", "provenance", "records"}
    data = _require_record(catalog, expected_top, "$.catalog")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise EvaluationManifestError("CATALOG_SCHEMA_VERSION", "$.catalog.schema_version")
    if data["catalog_kind"] != "development_only_known_examples":
        raise EvaluationManifestError("CATALOG_KIND", "$.catalog.catalog_kind")

    provenance = data["provenance"]
    provenance_keys = {
        "expanded_owner_example_count",
        "m1_hash_basis",
        "m1_manifest_path",
        "m1_manifest_sha256",
        "m1_run_id",
        "owner_artifact_hash_basis",
        "original_m1_count",
        "owner_feedback_file_sha256",
        "owner_feedback_path",
        "owner_section_hash_basis",
        "record_count",
        "tokenizer_id",
    }
    provenance = _require_record(provenance, provenance_keys, "$.catalog.provenance")
    expected_provenance = {
        "expanded_owner_example_count": 9,
        "m1_manifest_path": "tmp/router-rollout/mapping-pilot/m1/m1-20261105-02/manifest.json",
        "m1_manifest_sha256": _EXPECTED_M1_MANIFEST_SHA256,
        "m1_run_id": "m1-20261105-02",
        "owner_artifact_hash_basis": (
            "A-F schematic text blocks; G grid plus Builder-authored scene description; "
            "H grid plus player-facing arrival description; I grid plus Builder-authored "
            "arrival description; rating/review commentary excluded from artifact hashes "
            "and fingerprints"
        ),
        "original_m1_count": 16,
        "owner_feedback_file_sha256": _EXPECTED_OWNER_FEEDBACK_SHA256,
        "owner_feedback_path": "plans/v2-mapping-pilot-owner-feedback.md",
        "record_count": 25,
        "tokenizer_id": _TOKENIZER_ID,
    }
    for key, expected in expected_provenance.items():
        if provenance[key] != expected:
            raise EvaluationManifestError("CATALOG_PROVENANCE_PIN", "$.catalog.provenance." + key)
    if type(provenance["m1_hash_basis"]) is not str or not provenance["m1_hash_basis"].isascii():
        raise EvaluationManifestError("CATALOG_PROVENANCE", "$.catalog.provenance.m1_hash_basis")
    if type(provenance["owner_section_hash_basis"]) is not str or not provenance["owner_section_hash_basis"].isascii():
        raise EvaluationManifestError("CATALOG_PROVENANCE", "$.catalog.provenance.owner_section_hash_basis")

    records = data["records"]
    if type(records) is not list or len(records) != _MAX_KNOWN_RECORDS:
        raise EvaluationManifestError("CATALOG_RECORD_COUNT", "$.catalog.records")
    record_ids: list[str] = []
    for index, raw_record in enumerate(records):
        path = "$.catalog.records[%d]" % index
        if type(raw_record) is not dict:
            raise EvaluationManifestError("CATALOG_RECORD_TYPE", path)
        kind = raw_record.get("kind")
        base_keys = {
            "adaptation_lineage",
            "feature_tokens",
            "kind",
            "layout_tokens",
            "record_id",
            "source_identity",
            "source_identity_aliases",
            "source_path",
            "source_text_sha256",
        }
        expected_keys = (
            base_keys | {"source_section", "source_section_sha256"}
            if kind == "expanded_owner_example"
            else base_keys
        )
        record = _require_record(raw_record, expected_keys, path)
        record_id = record["record_id"]
        if type(record_id) is not str:
            raise EvaluationManifestError("CATALOG_RECORD_ID", path + ".record_id")
        record_ids.append(record_id)
        expected_kind = (
            "original_m1" if record_id.startswith("m1:") else "expanded_owner_example"
        )
        if kind != expected_kind:
            raise EvaluationManifestError("CATALOG_RECORD_KIND", path + ".kind")
        if type(record["source_identity"]) is not str or not record["source_identity"].isascii() or not record["source_identity"]:
            raise EvaluationManifestError("CATALOG_SOURCE_IDENTITY", path + ".source_identity")
        aliases = record["source_identity_aliases"]
        if type(aliases) is not list or not aliases or len(aliases) > 8:
            raise EvaluationManifestError("CATALOG_SOURCE_ALIASES", path + ".source_identity_aliases")
        if any(type(alias) is not str or not alias.isascii() or not alias for alias in aliases):
            raise EvaluationManifestError("CATALOG_SOURCE_ALIAS", path + ".source_identity_aliases")
        if len(set(aliases)) != len(aliases) or record["source_identity"] not in aliases:
            raise EvaluationManifestError("CATALOG_SOURCE_ALIAS", path + ".source_identity_aliases")
        source_path = record["source_path"]
        if type(source_path) is not str or not source_path.isascii() or source_path.startswith("/") or ".." in source_path.split("/"):
            raise EvaluationManifestError("CATALOG_SOURCE_PATH", path + ".source_path")
        _require_sha256(record["source_text_sha256"], path + ".source_text_sha256")
        _validate_token_list(record["layout_tokens"], path + ".layout_tokens", maximum=32)
        _validate_token_list(record["feature_tokens"], path + ".feature_tokens", maximum=32)
        if set(record["layout_tokens"]) & set(record["feature_tokens"]):
            raise EvaluationManifestError("CATALOG_FINGERPRINT_PARTITION", path)
        if len(set(record["layout_tokens"]) | set(record["feature_tokens"])) > 32:
            raise EvaluationManifestError("CATALOG_FINGERPRINT_LIMIT", path)
        lineage = record["adaptation_lineage"]
        if type(lineage) is not list or len(lineage) > _MAX_LINEAGE or any(
            type(item) is not str or not item.isascii() or not item for item in lineage
        ):
            raise EvaluationManifestError("CATALOG_LINEAGE", path + ".adaptation_lineage")
        if len(set(lineage)) != len(lineage):
            raise EvaluationManifestError("CATALOG_LINEAGE_DUPLICATE", path + ".adaptation_lineage")
        if kind == "original_m1":
            if not source_path.startswith(
                "tmp/router-rollout/mapping-pilot/m1/m1-20261105-02/"
            ) or not source_path.endswith(record_id[3:] + ".txt"):
                raise EvaluationManifestError("CATALOG_M1_PATH", path + ".source_path")
            if lineage:
                raise EvaluationManifestError("CATALOG_M1_LINEAGE", path + ".adaptation_lineage")
        else:
            expected_parent = _EXPECTED_OWNER_LINEAGE.get(record_id)
            if expected_parent is None or lineage != [expected_parent]:
                raise EvaluationManifestError("CATALOG_OWNER_LINEAGE", path + ".adaptation_lineage")
            if source_path != "plans/v2-mapping-pilot-owner-feedback.md":
                raise EvaluationManifestError("CATALOG_OWNER_PATH", path + ".source_path")
            section = record["source_section"]
            if type(section) is not str or not section.startswith("### ") or not section.isascii():
                raise EvaluationManifestError("CATALOG_OWNER_SECTION", path + ".source_section")
            _require_sha256(
                record["source_section_sha256"], path + ".source_section_sha256"
            )

    if len(set(record_ids)) != len(record_ids):
        raise EvaluationManifestError("CATALOG_DUPLICATE_RECORD", "$.catalog.records")
    expected_ids = set(_EXPECTED_M1_RECORD_IDS) | set(_EXPECTED_OWNER_RECORD_IDS)
    actual_ids = set(record_ids)
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    if missing:
        raise EvaluationManifestError("CATALOG_MISSING_RECORD", "$.catalog.records", missing[0])
    if extra:
        raise EvaluationManifestError("CATALOG_EXTRA_RECORD", "$.catalog.records", extra[0])

    digest = _hash_json(data)
    if digest != _EXPECTED_CATALOG_SHA256:
        raise EvaluationManifestError("CATALOG_HASH_MISMATCH", "$.catalog")
    return digest


def _validate_sha_inputs(
    test_sha256: object, rubric_sha256: object, assessor_sha256: object
) -> dict[str, str]:
    return {
        "test_sha256": _require_sha256(test_sha256, "$.protocol_hashes.test_sha256"),
        "rubric_sha256": _require_sha256(rubric_sha256, "$.protocol_hashes.rubric_sha256"),
        "assessor_sha256": _require_sha256(
            assessor_sha256, "$.protocol_hashes.assessor_sha256"
        ),
    }


def _normalize_input_tokens(value: object, path: str) -> list[str]:
    if type(value) is not list or len(value) > _MAX_EXPLICIT_TOKENS:
        raise EvaluationManifestError("INPUT_TOKEN_LIMIT", path)
    tokens: list[str] = []
    for token in value:
        if type(token) is not str or not _TOKEN_RE.fullmatch(token):
            raise EvaluationManifestError("INPUT_TOKEN_INVALID", path)
        tokens.append(token)
    if len(tokens) != len(set(tokens)):
        raise EvaluationManifestError("INPUT_TOKEN_DUPLICATE", path)
    return sorted(tokens)


def _normalize_scene_input(value: object, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    path = "$.scenes[%d]" % index
    expected_keys = {
        "scene_id",
        "source_identity",
        "source_ref",
        "source_text",
        "lineage_status",
        "adaptation_lineage",
        "layout_tokens",
        "feature_tokens",
        "projection_candidate",
        "projection_reference",
    }
    item = _require_record(value, expected_keys, path)
    scene_id = item["scene_id"]
    if type(scene_id) is not str or not _SCENE_ID_RE.fullmatch(scene_id):
        raise EvaluationManifestError("SCENE_ID", path + ".scene_id")
    identity = item["source_identity"]
    if type(identity) is not str or not identity or not identity.isascii() or len(identity) > _MAX_IDENTITY_CHARS:
        raise EvaluationManifestError("SOURCE_IDENTITY", path + ".source_identity")
    source_ref = item["source_ref"]
    if type(source_ref) is not str or not source_ref or not source_ref.isascii() or len(source_ref) > _MAX_SOURCE_REF_CHARS:
        raise EvaluationManifestError("SOURCE_REFERENCE", path + ".source_ref")
    source_text = item["source_text"]
    if type(source_text) is not str or not source_text.strip() or len(source_text) > _MAX_TEXT_CHARS:
        raise EvaluationManifestError("SOURCE_TEXT", path + ".source_text")
    try:
        source_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EvaluationManifestError("SOURCE_TEXT_ENCODING", path + ".source_text") from exc
    lineage_status = item["lineage_status"]
    if lineage_status not in ("independent", "derived"):
        raise EvaluationManifestError("LINEAGE_STATUS", path + ".lineage_status")
    lineage = item["adaptation_lineage"]
    if type(lineage) is not list or len(lineage) > _MAX_LINEAGE:
        raise EvaluationManifestError("LINEAGE_LIST", path + ".adaptation_lineage")
    if any(type(entry) is not str or not entry.isascii() or not entry or len(entry) > 512 for entry in lineage):
        raise EvaluationManifestError("LINEAGE_ENTRY", path + ".adaptation_lineage")
    if len(set(lineage)) != len(lineage):
        raise EvaluationManifestError("LINEAGE_DUPLICATE", path + ".adaptation_lineage")
    if (lineage_status == "independent" and lineage) or (
        lineage_status == "derived" and not lineage
    ):
        raise EvaluationManifestError("LINEAGE_STATUS_CONFLICT", path + ".adaptation_lineage")
    layout_tokens = _normalize_input_tokens(item["layout_tokens"], path + ".layout_tokens")
    feature_tokens = _normalize_input_tokens(item["feature_tokens"], path + ".feature_tokens")
    projection_candidate = copy.deepcopy(item["projection_candidate"])
    projection_reference = copy.deepcopy(item["projection_reference"])
    if type(projection_candidate) is not dict or type(projection_reference) is not dict:
        raise EvaluationManifestError("PROJECTION_INPUT_OBJECT", path + ".projection_candidate")
    if projection_candidate.get("fixture_id") != scene_id:
        raise EvaluationManifestError("PROJECTION_SCENE_BINDING", path + ".projection_candidate.fixture_id")

    fingerprints = fingerprint_source_text(source_text)
    if layout_tokens != fingerprints["layout_tokens"]:
        raise EvaluationManifestError(
            "SOURCE_LAYOUT_FINGERPRINT_MISMATCH", path + ".layout_tokens"
        )
    if feature_tokens != fingerprints["feature_tokens"]:
        raise EvaluationManifestError(
            "SOURCE_FEATURE_FINGERPRINT_MISMATCH", path + ".feature_tokens"
        )
    source = {
        "identity": identity,
        "reference": source_ref,
        "source_text_sha256": _hash_text(source_text),
        "lineage_status": lineage_status,
        "adaptation_lineage": sorted(lineage),
        "text_tokens": fingerprints["text_tokens"],
        "text_fingerprint_sha256": fingerprints["text_fingerprint_sha256"],
        "layout_tokens": layout_tokens,
        "layout_fingerprint_sha256": _hash_json(layout_tokens),
        "feature_tokens": feature_tokens,
        "feature_fingerprint_sha256": _hash_json(feature_tokens),
    }
    projection_input = {
        "candidate": projection_candidate,
        "reference": projection_reference,
    }
    return {"scene_id": scene_id, "source": source}, projection_input


def _artifact_record(condition: str, output: dict[str, Any], path: str) -> dict[str, Any]:
    content = output.get("content")
    if type(content) is not str or len(content) > _MAX_ARTIFACT_CHARS:
        raise EvaluationManifestError("ARTIFACT_CONTENT_LIMIT", path + ".content")
    hashes = output.get("hashes")
    expected_hashes = {
        "content_sha256",
        "fact_set_sha256",
        "topology_sha256",
        "provenance_sha256",
        "artifact_sha256",
    }
    hashes = _require_record(hashes, expected_hashes, path + ".hashes")
    for key, value in hashes.items():
        _require_sha256(value, path + ".hashes." + key)
    if _hash_text(content) != hashes["content_sha256"]:
        raise EvaluationManifestError("ARTIFACT_CONTENT_HASH", path + ".content")
    result = {
        "condition": condition,
        "content_type": output.get("content_type"),
        "content": content,
        "hashes": copy.deepcopy(hashes),
    }
    if condition == "D":
        result["staging_claim_bindings"] = copy.deepcopy(
            output.get("staging_claim_bindings", [])
        )
    return result


def _overlap_metrics(left: list[str], right: list[str]) -> dict[str, Any]:
    left_set = set(left)
    right_set = set(right)
    shared = sorted(left_set & right_set)
    union_count = len(left_set | right_set)
    similarity_ppm = (len(shared) * 1_000_000 // union_count) if union_count else 0
    return {
        "shared_count": len(shared),
        "union_count": union_count,
        "similarity_ppm": similarity_ppm,
        "shared_tokens": shared,
    }


def _requires_review(
    metrics: dict[str, Any], *, minimum_shared: int, minimum_ppm: int
) -> bool:
    return bool(metrics["shared_count"]) and (
        metrics["shared_count"] >= minimum_shared
        and metrics["similarity_ppm"] >= minimum_ppm
        or metrics["similarity_ppm"] == 1_000_000
    )


def _leakage_policy() -> dict[str, Any]:
    return {
        "exact_identity_reference_text_or_section_hash_ancestry_and_artifact_hash": "reject",
        "unresolved_declared_derivative": "reject",
        "token_overlap_metric": "integer Jaccard similarity in parts per million",
        "source_text_overlap": {
            "minimum_shared_tokens": _TEXT_OVERLAP_MIN_SHARED,
            "minimum_jaccard_ppm": _TEXT_OVERLAP_MIN_JACCARD_PPM,
            "exact_token_set_overlap": "review_required",
        },
        "artifact_text_overlap": {
            "minimum_shared_tokens": _TEXT_OVERLAP_MIN_SHARED,
            "minimum_jaccard_ppm": _TEXT_OVERLAP_MIN_JACCARD_PPM,
            "exact_token_set_overlap": "review_required",
        },
        "layout_fingerprint_overlap": {
            "minimum_shared_tokens": _LAYOUT_OVERLAP_MIN_SHARED,
            "minimum_jaccard_ppm": _LAYOUT_OVERLAP_MIN_JACCARD_PPM,
            "exact_token_set_overlap": "review_required",
        },
        "feature_fingerprint_overlap": {
            "minimum_shared_tokens": _FEATURE_OVERLAP_MIN_SHARED,
            "minimum_jaccard_ppm": _FEATURE_OVERLAP_MIN_JACCARD_PPM,
            "exact_token_set_overlap": "review_required",
        },
        "semantic_detection_claim": "none; bounded lexical/layout/feature screens only",
    }


def _known_text_tokens(record: dict[str, Any]) -> list[str]:
    return sorted(set(record["layout_tokens"]) | set(record["feature_tokens"]))


def _make_pair_check(
    scene: dict[str, Any],
    known: dict[str, Any],
) -> dict[str, Any]:
    source = scene["source"]
    known_ids = set(
        [known["record_id"], known["source_identity"], known["source_path"]]
        + known["source_identity_aliases"]
    )
    candidate_lineage = set(source["adaptation_lineage"])
    lineage_matches = sorted(candidate_lineage & known_ids)
    identity_matches = source["identity"] in set(
        [known["record_id"], known["source_identity"]]
        + known["source_identity_aliases"]
    )
    reference_matches = source["reference"] in set(
        [known["source_path"]] + known["source_identity_aliases"]
    )
    source_hash_match = source["source_text_sha256"] == known["source_text_sha256"]
    known_section_hash = known.get("source_section_sha256")
    source_section_hash_match = (
        type(known_section_hash) is str
        and source["source_text_sha256"] == known_section_hash
    )
    artifact_hash_matches: list[str] = []
    artifact_text_overlaps: list[dict[str, Any]] = []
    known_tokens = _known_text_tokens(known)
    known_hashes = {known["source_text_sha256"]}
    if type(known_section_hash) is str:
        known_hashes.add(known_section_hash)
    for artifact in scene["artifacts"]:
        condition = artifact["condition"]
        if known_hashes & {
            artifact["hashes"]["content_sha256"],
            artifact["hashes"]["artifact_sha256"],
        }:
            artifact_hash_matches.append(condition)
        metrics = _overlap_metrics(
            _selected_text_tokens(artifact["content"]), known_tokens
        )
        artifact_text_overlaps.append({"condition": condition, **metrics})

    text_overlap = _overlap_metrics(source["text_tokens"], known_tokens)
    layout_overlap = _overlap_metrics(source["layout_tokens"], known["layout_tokens"])
    feature_overlap = _overlap_metrics(source["feature_tokens"], known["feature_tokens"])
    flags: list[str] = []
    if identity_matches:
        flags.append("EXACT_SOURCE_IDENTITY")
    if reference_matches:
        flags.append("EXACT_SOURCE_REFERENCE")
    if source_hash_match:
        flags.append("EXACT_SOURCE_TEXT_SHA256")
    if source_section_hash_match:
        flags.append("EXACT_SOURCE_SECTION_SHA256")
    if lineage_matches:
        flags.append("DECLARED_KNOWN_ANCESTOR")
    if artifact_hash_matches:
        flags.append("EXACT_ARTIFACT_HASH")
    if source["lineage_status"] == "derived" and not lineage_matches:
        flags.append("UNRESOLVED_DERIVATIVE_LINEAGE")

    review_flags: list[str] = []
    if _requires_review(
        text_overlap,
        minimum_shared=_TEXT_OVERLAP_MIN_SHARED,
        minimum_ppm=_TEXT_OVERLAP_MIN_JACCARD_PPM,
    ):
        review_flags.append("TEXT_TOKEN_OVERLAP_REVIEW")
    if any(
        _requires_review(
            item,
            minimum_shared=_TEXT_OVERLAP_MIN_SHARED,
            minimum_ppm=_TEXT_OVERLAP_MIN_JACCARD_PPM,
        )
        for item in artifact_text_overlaps
    ):
        review_flags.append("ARTIFACT_TEXT_OVERLAP_REVIEW")
    if _requires_review(
        layout_overlap,
        minimum_shared=_LAYOUT_OVERLAP_MIN_SHARED,
        minimum_ppm=_LAYOUT_OVERLAP_MIN_JACCARD_PPM,
    ):
        review_flags.append("LAYOUT_FINGERPRINT_REVIEW")
    if _requires_review(
        feature_overlap,
        minimum_shared=_FEATURE_OVERLAP_MIN_SHARED,
        minimum_ppm=_FEATURE_OVERLAP_MIN_JACCARD_PPM,
    ):
        review_flags.append("FEATURE_FINGERPRINT_REVIEW")

    if flags:
        verdict = "REJECT"
    elif review_flags:
        verdict = "REVIEW_REQUIRED"
    else:
        verdict = "NO_MATCH_WITHIN_BOUNDED_CHECKS"
    return {
        "scene_id": scene["scene_id"],
        "known_record_id": known["record_id"],
        "known_record_kind": known["kind"],
        "source_identity_match": identity_matches,
        "source_reference_match": reference_matches,
        "source_text_sha256_match": source_hash_match,
        "source_section_sha256_match": source_section_hash_match,
        "declared_lineage_matches": lineage_matches,
        "artifact_hash_matches": artifact_hash_matches,
        "text_overlap": text_overlap,
        "artifact_text_overlap": artifact_text_overlaps,
        "layout_overlap": layout_overlap,
        "feature_overlap": feature_overlap,
        "flags": flags,
        "review_flags": review_flags,
        "verdict": verdict,
    }


def _build_leakage_checks(
    scenes: list[dict[str, Any]], catalog_records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    checks = [
        _make_pair_check(scene, known)
        for scene in scenes
        for known in sorted(catalog_records, key=lambda item: item["record_id"])
    ]
    counts = Counter(check["verdict"] for check in checks)
    status = (
        "REJECTED"
        if counts["REJECT"]
        else "REVIEW_REQUIRED"
        if counts["REVIEW_REQUIRED"]
        else "NO_KNOWN_MATCH"
    )
    summary = {
        "pair_checks": len(checks),
        "pairs_per_scene": len(catalog_records),
        "rejected_pairs": counts["REJECT"],
        "review_required_pairs": counts["REVIEW_REQUIRED"],
        "no_match_pairs": counts["NO_MATCH_WITHIN_BOUNDED_CHECKS"],
        "status": status,
        "policy": _leakage_policy(),
    }
    return checks, summary, status


def _stable_order(seed: str, item_ids: list[str]) -> list[str]:
    seed_bytes = seed.encode("ascii")

    def rank(item_id: str) -> tuple[str, str]:
        digest = hashlib.sha256(
            b"mise-en-scene-assignment-v1\x00" + seed_bytes + b"\x00" + item_id.encode("ascii")
        ).hexdigest()
        return digest, item_id

    return sorted(item_ids, key=rank)


def _build_assignment(scene_ids: list[str], seed: str) -> dict[str, Any]:
    artifact_records = [
        {
            "artifact_id": scene_id + "|" + condition,
            "scene_id": scene_id,
            "condition": condition,
        }
        for scene_id in scene_ids
        for condition in _CONDITIONS
    ]
    episode_records = [
        {
            "episode_id": scene_id + "|" + condition + "|" + party_shape,
            "scene_id": scene_id,
            "condition": condition,
            "party_shape": party_shape,
        }
        for scene_id in scene_ids
        for condition in _CONDITIONS
        for party_shape in _PARTY_SHAPES
    ]
    artifact_by_id = {item["artifact_id"]: item for item in artifact_records}
    episode_by_id = {item["episode_id"]: item for item in episode_records}
    artifact_order = _stable_order(seed, list(artifact_by_id))
    episode_order = _stable_order(seed, list(episode_by_id))
    seed_sha256 = hashlib.sha256(seed.encode("ascii")).hexdigest()
    artifact_order_sha256 = _hash_json(artifact_order)
    episode_order_sha256 = _hash_json(episode_order)
    order_sha256 = _hash_json(
        {
            "algorithm": "sha256-rank-v1",
            "assignment_seed_sha256": seed_sha256,
            "artifact_order": artifact_order,
            "episode_order": episode_order,
        }
    )
    return {
        "algorithm": "sha256-rank-v1",
        "seed": seed,
        "seed_sha256": seed_sha256,
        "artifact_order": [artifact_by_id[item] for item in artifact_order],
        "episode_order": [episode_by_id[item] for item in episode_order],
        "artifact_order_sha256": artifact_order_sha256,
        "episode_order_sha256": episode_order_sha256,
        "order_sha256": order_sha256,
    }


def _hash_envelope(manifest: dict[str, Any]) -> dict[str, str]:
    scenes = manifest["scenes"]
    assignment = manifest["assignment"]
    artifact_order_ids = [item["artifact_id"] for item in assignment["artifact_order"]]
    episode_order_ids = [item["episode_id"] for item in assignment["episode_order"]]
    return {
        "sources_sha256": _hash_json(
            [{"scene_id": scene["scene_id"], "source": scene["source"]} for scene in scenes]
        ),
        "facts_sha256": _hash_json(
            [
                {"scene_id": scene["scene_id"], "fact_binding": scene["fact_binding"]}
                for scene in scenes
            ]
        ),
        "artifacts_sha256": _hash_json(
            [
                {
                    "scene_id": scene["scene_id"],
                    "artifacts": scene["artifacts"],
                }
                for scene in scenes
            ]
        ),
        "fixtures_sha256": _hash_json(
            [
                {
                    "scene_id": scene["scene_id"],
                    "projection_input": scene["projection_input"],
                }
                for scene in scenes
            ]
        ),
        "test_sha256": manifest["protocol_hashes"]["test_sha256"],
        "rubric_sha256": manifest["protocol_hashes"]["rubric_sha256"],
        "assessor_sha256": manifest["protocol_hashes"]["assessor_sha256"],
        "assignment_seed_sha256": assignment["seed_sha256"],
        "artifact_order_sha256": assignment["artifact_order_sha256"],
        "episode_order_sha256": assignment["episode_order_sha256"],
        "order_sha256": assignment["order_sha256"],
        "catalog_sha256": manifest["catalog"]["sha256"],
        "leakage_review_sha256": _hash_json(
            {
                "checks": manifest["leakage_checks"],
                "summary": manifest["leakage_summary"],
                "status": manifest["leakage_status"],
            }
        ),
        "counts_sha256": _hash_json(manifest["counts"]),
    }


def _manifest_candidate_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: manifest[key]
        for key in (
            "schema_version",
            "manifest_kind",
            "trace",
            "counts",
            "catalog",
            "protocol_hashes",
            "scenes",
            "leakage_checks",
            "leakage_summary",
            "leakage_status",
            "assignment",
            "hashes",
        )
    }


def build_proposed_holdout_manifest(
    scenes: object,
    assignment_seed: object,
    *,
    test_sha256: object,
    rubric_sha256: object,
    assessor_sha256: object,
    catalog: object | None = None,
) -> dict[str, Any]:
    """Build an unauthorized six-scene proposal with 24 projections and 48 episodes.

    This function computes projections through the existing R6 projection
    builder, records every scene-to-known-record leakage pair, and performs no
    scoring, persistence, network access, or provider call.
    """

    selected_catalog = load_known_examples() if catalog is None else copy.deepcopy(catalog)
    catalog_sha256 = validate_known_examples(selected_catalog)
    if type(scenes) is not list or len(scenes) != _MAX_SCENES:
        raise EvaluationManifestError("SCENE_COUNT_EXACTLY_SIX", "$.scenes")
    if type(assignment_seed) is not str or not assignment_seed or not assignment_seed.isascii() or len(assignment_seed) > 256:
        raise EvaluationManifestError("ASSIGNMENT_SEED", "$.assignment_seed")
    protocol_hashes = _validate_sha_inputs(test_sha256, rubric_sha256, assessor_sha256)

    normalized_scenes: list[dict[str, Any]] = []
    scene_ids: set[str] = set()
    source_identities: set[str] = set()
    for index, raw_scene in enumerate(scenes):
        scene, projection_input = _normalize_scene_input(raw_scene, index)
        if scene["scene_id"] in scene_ids:
            raise EvaluationManifestError("DUPLICATE_SCENE_ID", "$.scenes[%d].scene_id" % index)
        if scene["source"]["identity"] in source_identities:
            raise EvaluationManifestError(
                "DUPLICATE_SOURCE_IDENTITY", "$.scenes[%d].source_identity" % index
            )
        scene_ids.add(scene["scene_id"])
        source_identities.add(scene["source"]["identity"])
        try:
            outputs = projections.build_matched_projections(
                projection_input["candidate"],
                projection_input["reference"],
                audience="public",
            )
        except projections.ProjectionError as exc:
            raise EvaluationManifestError(
                "PROJECTION_INPUT_INVALID", "$.scenes[%d].projection_input" % index,
                {"code": exc.code, "path": exc.path},
            ) from exc
        if set(outputs) != set(_CONDITIONS):
            raise EvaluationManifestError("PROJECTION_CONDITIONS", "$.scenes[%d]" % index)
        artifacts = [
            _artifact_record(
                condition,
                outputs[condition],
                "$.scenes[%d].artifacts[%s]" % (index, condition),
            )
            for condition in _CONDITIONS
        ]
        binding = copy.deepcopy(outputs["A"]["binding"])
        if any(
            _canonical_json(outputs[condition]["binding"]) != _canonical_json(binding)
            for condition in _CONDITIONS
        ):
            raise EvaluationManifestError("MATCHED_FACT_BINDING_MISMATCH", "$.scenes[%d]" % index)
        normalized_scenes.append(
            {
                **scene,
                "projection_input": projection_input,
                "fact_binding": binding,
                "artifacts": artifacts,
            }
        )

    catalog_records = selected_catalog["records"]
    leakage_checks, leakage_summary, leakage_status = _build_leakage_checks(
        normalized_scenes, catalog_records
    )
    assignment = _build_assignment(
        [scene["scene_id"] for scene in normalized_scenes], assignment_seed
    )
    artifact_count = sum(len(scene["artifacts"]) for scene in normalized_scenes)
    episode_count = len(assignment["episode_order"])
    if artifact_count != 24 or episode_count != 48:
        raise EvaluationManifestError("PROPOSED_MATRIX_COUNTS", "$.counts")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_kind": "proposed_mise_en_scene_holdout",
        "trace": "R8",
        "status": "PROPOSED",
        "authorization_status": "NOT_AUTHORIZED",
        "scoring_status": "NOT_STARTED",
        "counts": {
            "scenes": 6,
            "artifacts": 24,
            "conditions": list(_CONDITIONS),
            "episodes": 48,
            "party_shapes": list(_PARTY_SHAPES),
        },
        "catalog": {
            "kind": "development_only_known_examples",
            "sha256": catalog_sha256,
            "original_m1_records": 16,
            "expanded_owner_examples": 9,
            "pair_checks": 150,
        },
        "protocol_hashes": protocol_hashes,
        "scenes": normalized_scenes,
        "leakage_checks": leakage_checks,
        "leakage_summary": leakage_summary,
        "leakage_status": leakage_status,
        "assignment": assignment,
        "hashes": {},
    }
    manifest["hashes"] = _hash_envelope(manifest)
    manifest["candidate_sha256"] = _hash_json(_manifest_candidate_payload(manifest))
    if len(_canonical_json(manifest).encode("ascii")) > _MAX_MANIFEST_BYTES:
        raise EvaluationManifestError("MANIFEST_SIZE_LIMIT", "$")
    return manifest


def _verify_manifest_shell(manifest: object) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "manifest_kind",
        "trace",
        "status",
        "authorization_status",
        "scoring_status",
        "counts",
        "catalog",
        "protocol_hashes",
        "scenes",
        "leakage_checks",
        "leakage_summary",
        "leakage_status",
        "assignment",
        "hashes",
        "candidate_sha256",
    }
    data = _require_record(manifest, expected_keys, "$.manifest")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise EvaluationManifestError("MANIFEST_SCHEMA_VERSION", "$.manifest.schema_version")
    if data["manifest_kind"] != "proposed_mise_en_scene_holdout" or data["trace"] != "R8":
        raise EvaluationManifestError("MANIFEST_KIND", "$.manifest")
    if data["status"] != "PROPOSED" or data["authorization_status"] != "NOT_AUTHORIZED":
        raise EvaluationManifestError("MANIFEST_AUTHORITY_STATE", "$.manifest.status")
    if data["scoring_status"] != "NOT_STARTED":
        raise EvaluationManifestError("SCORING_NOT_ALLOWED", "$.manifest.scoring_status")
    return data


def verify_proposed_manifest(
    manifest: object, *, catalog: object | None = None
) -> dict[str, Any]:
    """Recompute projections, leakage pairs, assignment, and all envelope hashes."""

    data = _verify_manifest_shell(manifest)
    selected_catalog = load_known_examples() if catalog is None else copy.deepcopy(catalog)
    catalog_sha256 = validate_known_examples(selected_catalog)
    catalog_binding = _require_record(
        data["catalog"],
        {"kind", "sha256", "original_m1_records", "expanded_owner_examples", "pair_checks"},
        "$.manifest.catalog",
    )
    if catalog_binding != {
        "kind": "development_only_known_examples",
        "sha256": catalog_sha256,
        "original_m1_records": 16,
        "expanded_owner_examples": 9,
        "pair_checks": 150,
    }:
        raise EvaluationManifestError("CATALOG_BINDING_STALE", "$.manifest.catalog")

    protocol_hashes = _require_record(
        data["protocol_hashes"],
        {"test_sha256", "rubric_sha256", "assessor_sha256"},
        "$.manifest.protocol_hashes",
    )
    _validate_sha_inputs(
        protocol_hashes["test_sha256"],
        protocol_hashes["rubric_sha256"],
        protocol_hashes["assessor_sha256"],
    )
    scenes = data["scenes"]
    if type(scenes) is not list or len(scenes) != _MAX_SCENES:
        raise EvaluationManifestError("SCENE_COUNT_EXACTLY_SIX", "$.manifest.scenes")
    scene_ids: list[str] = []
    scene_id_set: set[str] = set()
    source_identity_set: set[str] = set()
    for index, scene in enumerate(scenes):
        path = "$.manifest.scenes[%d]" % index
        scene = _require_record(
            scene,
            {"scene_id", "source", "projection_input", "fact_binding", "artifacts"},
            path,
        )
        scene_id = scene["scene_id"]
        if type(scene_id) is not str or not _SCENE_ID_RE.fullmatch(scene_id):
            raise EvaluationManifestError("SCENE_ID", path + ".scene_id")
        if scene_id in scene_id_set:
            raise EvaluationManifestError("DUPLICATE_SCENE_ID", path + ".scene_id")
        scene_id_set.add(scene_id)
        scene_ids.append(scene_id)
        source = _require_record(
            scene["source"],
            {
                "identity",
                "reference",
                "source_text_sha256",
                "lineage_status",
                "adaptation_lineage",
                "text_tokens",
                "text_fingerprint_sha256",
                "layout_tokens",
                "layout_fingerprint_sha256",
                "feature_tokens",
                "feature_fingerprint_sha256",
            },
            path + ".source",
        )
        identity = source["identity"]
        if (
            type(identity) is not str
            or not identity
            or not identity.isascii()
            or len(identity) > _MAX_IDENTITY_CHARS
        ):
            raise EvaluationManifestError("SOURCE_IDENTITY", path + ".source.identity")
        if identity in source_identity_set:
            raise EvaluationManifestError(
                "DUPLICATE_SOURCE_IDENTITY", path + ".source.identity"
            )
        source_identity_set.add(identity)
        reference = source["reference"]
        if (
            type(reference) is not str
            or not reference
            or not reference.isascii()
            or len(reference) > _MAX_SOURCE_REF_CHARS
        ):
            raise EvaluationManifestError("SOURCE_REFERENCE", path + ".source.reference")
        _require_sha256(source["source_text_sha256"], path + ".source.source_text_sha256")
        _require_sha256(source["text_fingerprint_sha256"], path + ".source.text_fingerprint_sha256")
        _require_sha256(source["layout_fingerprint_sha256"], path + ".source.layout_fingerprint_sha256")
        _require_sha256(source["feature_fingerprint_sha256"], path + ".source.feature_fingerprint_sha256")
        text_tokens = _validate_token_list(
            source["text_tokens"], path + ".source.text_tokens", maximum=32
        )
        layout_tokens = _validate_token_list(
            source["layout_tokens"], path + ".source.layout_tokens", maximum=32
        )
        feature_tokens = _validate_token_list(
            source["feature_tokens"], path + ".source.feature_tokens", maximum=32
        )
        if set(layout_tokens) & set(feature_tokens):
            raise EvaluationManifestError(
                "SOURCE_FINGERPRINT_PARTITION", path + ".source"
            )
        if set(layout_tokens) | set(feature_tokens) != set(text_tokens):
            raise EvaluationManifestError(
                "SOURCE_FINGERPRINT_PARTITION", path + ".source"
            )
        if layout_tokens != sorted(set(text_tokens) & _LAYOUT_TERMS):
            raise EvaluationManifestError(
                "LAYOUT_FINGERPRINT_STALE", path + ".source.layout_tokens"
            )
        if feature_tokens != sorted(set(text_tokens) - _LAYOUT_TERMS):
            raise EvaluationManifestError(
                "FEATURE_FINGERPRINT_STALE", path + ".source.feature_tokens"
            )
        if source["text_fingerprint_sha256"] != _hash_json(source["text_tokens"]):
            raise EvaluationManifestError("SOURCE_TEXT_FINGERPRINT_STALE", path + ".source.text_tokens")
        if source["layout_fingerprint_sha256"] != _hash_json(source["layout_tokens"]):
            raise EvaluationManifestError("LAYOUT_FINGERPRINT_STALE", path + ".source.layout_tokens")
        if source["feature_fingerprint_sha256"] != _hash_json(source["feature_tokens"]):
            raise EvaluationManifestError("FEATURE_FINGERPRINT_STALE", path + ".source.feature_tokens")
        if source["lineage_status"] not in ("independent", "derived"):
            raise EvaluationManifestError("LINEAGE_STATUS", path + ".source.lineage_status")
        lineage = source["adaptation_lineage"]
        if type(lineage) is not list or len(lineage) > _MAX_LINEAGE:
            raise EvaluationManifestError("LINEAGE_LIST", path + ".source.adaptation_lineage")
        if any(
            type(entry) is not str
            or not entry
            or not entry.isascii()
            or len(entry) > 512
            for entry in lineage
        ):
            raise EvaluationManifestError(
                "LINEAGE_ENTRY", path + ".source.adaptation_lineage"
            )
        if len(set(lineage)) != len(lineage):
            raise EvaluationManifestError(
                "LINEAGE_DUPLICATE", path + ".source.adaptation_lineage"
            )
        if lineage != sorted(lineage):
            raise EvaluationManifestError(
                "LINEAGE_NOT_CANONICAL", path + ".source.adaptation_lineage"
            )
        if source["lineage_status"] == "independent" and lineage:
            raise EvaluationManifestError("LINEAGE_STATUS_CONFLICT", path + ".source.adaptation_lineage")
        if source["lineage_status"] == "derived" and not lineage:
            raise EvaluationManifestError("LINEAGE_STATUS_CONFLICT", path + ".source.adaptation_lineage")

        projection_input = _require_record(
            scene["projection_input"], {"candidate", "reference"}, path + ".projection_input"
        )
        try:
            outputs = projections.build_matched_projections(
                projection_input["candidate"],
                projection_input["reference"],
                audience="public",
            )
        except projections.ProjectionError as exc:
            raise EvaluationManifestError(
                "PROJECTION_INPUT_INVALID", path + ".projection_input",
                {"code": exc.code, "path": exc.path},
            ) from exc
        if projection_input["candidate"].get("fixture_id") != scene_id:
            raise EvaluationManifestError("PROJECTION_SCENE_BINDING", path + ".projection_input")
        expected_binding = outputs["A"]["binding"]
        if _canonical_json(scene["fact_binding"]) != _canonical_json(expected_binding):
            raise EvaluationManifestError("FACT_BINDING_STALE", path + ".fact_binding")
        artifacts = scene["artifacts"]
        if type(artifacts) is not list or len(artifacts) != 4:
            raise EvaluationManifestError("ARTIFACT_COUNT_PER_SCENE", path + ".artifacts")
        artifact_conditions: list[str] = []
        for artifact_index, artifact in enumerate(artifacts):
            artifact_path = path + ".artifacts[%d]" % artifact_index
            if type(artifact) is not dict:
                raise EvaluationManifestError("ARTIFACT_RECORD_TYPE", artifact_path)
            condition = artifact.get("condition")
            if condition not in _CONDITIONS:
                raise EvaluationManifestError("ARTIFACT_CONDITION", artifact_path + ".condition")
            artifact_conditions.append(condition)
            expected_artifact = _artifact_record(condition, outputs[condition], artifact_path)
            if _canonical_json(artifact) != _canonical_json(expected_artifact):
                raise EvaluationManifestError("PROJECTION_ARTIFACT_STALE", artifact_path)
        if set(artifact_conditions) != set(_CONDITIONS) or len(set(artifact_conditions)) != 4:
            raise EvaluationManifestError("ARTIFACT_CONDITION_MATRIX", path + ".artifacts")
    if len(set(scene_ids)) != _MAX_SCENES:
        raise EvaluationManifestError("DUPLICATE_SCENE_ID", "$.manifest.scenes")

    counts = _require_record(
        data["counts"],
        {"scenes", "artifacts", "conditions", "episodes", "party_shapes"},
        "$.manifest.counts",
    )
    if counts != {
        "scenes": 6,
        "artifacts": 24,
        "conditions": list(_CONDITIONS),
        "episodes": 48,
        "party_shapes": list(_PARTY_SHAPES),
    }:
        raise EvaluationManifestError("MANIFEST_COUNTS_STALE", "$.manifest.counts")

    assignment = data["assignment"]
    if type(assignment) is not dict or assignment.get("algorithm") != "sha256-rank-v1":
        raise EvaluationManifestError("ASSIGNMENT_SHAPE", "$.manifest.assignment")
    seed = assignment.get("seed")
    if type(seed) is not str or not seed or not seed.isascii() or len(seed) > 256:
        raise EvaluationManifestError("ASSIGNMENT_SEED", "$.manifest.assignment.seed")
    expected_assignment = _build_assignment(scene_ids, seed)
    if _canonical_json(assignment) != _canonical_json(expected_assignment):
        raise EvaluationManifestError("ASSIGNMENT_ORDER_STALE", "$.manifest.assignment")

    leakage_checks, leakage_summary, leakage_status = _build_leakage_checks(
        scenes, selected_catalog["records"]
    )
    if _canonical_json(data["leakage_checks"]) != _canonical_json(leakage_checks):
        raise EvaluationManifestError("LEAKAGE_REVIEW_STALE", "$.manifest.leakage_checks")
    if _canonical_json(data["leakage_summary"]) != _canonical_json(leakage_summary):
        raise EvaluationManifestError("LEAKAGE_SUMMARY_STALE", "$.manifest.leakage_summary")
    if data["leakage_status"] != leakage_status:
        raise EvaluationManifestError("LEAKAGE_STATUS_STALE", "$.manifest.leakage_status")

    hashes = _require_record(
        data["hashes"],
        {
            "sources_sha256",
            "facts_sha256",
            "artifacts_sha256",
            "fixtures_sha256",
            "test_sha256",
            "rubric_sha256",
            "assessor_sha256",
            "assignment_seed_sha256",
            "artifact_order_sha256",
            "episode_order_sha256",
            "order_sha256",
            "catalog_sha256",
            "leakage_review_sha256",
            "counts_sha256",
        },
        "$.manifest.hashes",
    )
    recomputed_hashes = _hash_envelope(data)
    if _canonical_json(hashes) != _canonical_json(recomputed_hashes):
        raise EvaluationManifestError("HASH_ENVELOPE_STALE", "$.manifest.hashes")
    candidate_sha256 = _require_sha256(data["candidate_sha256"], "$.manifest.candidate_sha256")
    expected_candidate_sha256 = _hash_json(_manifest_candidate_payload(data))
    if candidate_sha256 != expected_candidate_sha256:
        raise EvaluationManifestError("MANIFEST_HASH_STALE", "$.manifest.candidate_sha256")
    if len(_canonical_json(data).encode("ascii")) > _MAX_MANIFEST_BYTES:
        raise EvaluationManifestError("MANIFEST_SIZE_LIMIT", "$.manifest")
    return {
        "is_valid": True,
        "candidate_sha256": candidate_sha256,
        "catalog_sha256": catalog_sha256,
        "pair_checks": len(leakage_checks),
        "leakage_status": leakage_status,
        "artifact_count": 24,
        "episode_count": 48,
    }


def freeze_manifest_binding(
    manifest: object,
    approval_record: object,
    *,
    catalog: object | None = None,
) -> dict[str, Any]:
    """Verify an exact external approval binding; never authenticate or authorize it.

    A synthetic test record must use ``test_only=True`` and a
    ``synthetic-test-only:`` reference. The returned binding never authorizes
    scoring or a live evaluation.
    """

    report = verify_proposed_manifest(manifest, catalog=catalog)
    data = _verify_manifest_shell(manifest)
    if data["leakage_status"] != "NO_KNOWN_MATCH":
        code = (
            "KNOWN_LEAKAGE_REJECTED"
            if data["leakage_status"] == "REJECTED"
            else "LEAKAGE_REVIEW_REQUIRED"
        )
        raise EvaluationManifestError(code, "$.manifest.leakage_status")
    approval_keys = {
        "approval_reference",
        "candidate_sha256",
        "assignment_seed_sha256",
        "order_sha256",
        "test_only",
    }
    approval = _require_record(approval_record, approval_keys, "$.approval_record")
    reference = approval["approval_reference"]
    if type(reference) is not str or not reference or not reference.isascii() or len(reference) > 512:
        raise EvaluationManifestError("OWNER_APPROVAL_REQUIRED", "$.approval_record.approval_reference")
    test_only = approval["test_only"]
    if type(test_only) is not bool:
        raise EvaluationManifestError("APPROVAL_TEST_MARKER", "$.approval_record.test_only")
    is_synthetic_reference = reference.startswith("synthetic-test-only:")
    if test_only != is_synthetic_reference:
        raise EvaluationManifestError("SYNTHETIC_APPROVAL_LABEL", "$.approval_record.approval_reference")
    for key in ("candidate_sha256", "assignment_seed_sha256", "order_sha256"):
        _require_sha256(approval[key], "$.approval_record." + key)

    expected_bindings = {
        "candidate_sha256": report["candidate_sha256"],
        "assignment_seed_sha256": data["assignment"]["seed_sha256"],
        "order_sha256": data["assignment"]["order_sha256"],
    }
    if any(approval[key] != expected for key, expected in expected_bindings.items()):
        raise EvaluationManifestError("REAPPROVAL_REQUIRED", "$.approval_record")

    binding: dict[str, Any] = {
        "schema_version": 1,
        "status": "TEST_ONLY_BINDING_VERIFIED"
        if test_only
        else "BINDING_VERIFIED_NOT_AUTHENTICATED",
        "authorization_status": "NOT_AUTHORIZED",
        "scoring_status": "NOT_STARTED",
        "approval_reference": reference,
        "candidate_sha256": report["candidate_sha256"],
        "assignment": copy.deepcopy(data["assignment"]),
        "freeze_hashes": copy.deepcopy(data["hashes"]),
        "human_identity_authenticated": False,
        "scoring_authorized": False,
    }
    binding["binding_sha256"] = _hash_json(binding)
    return binding
