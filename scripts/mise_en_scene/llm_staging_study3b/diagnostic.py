# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Primary-only, in-memory Study 3 ha003 guarded-marker presence diagnostic."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from ..llm_staging.transport import _canonical_bytes as _transport_canonical_bytes
from .study3_compat import contract as study3_contract
from .study3_compat import newrequest as study3_request


# TABLETOP MODE: Do not read, persist, log, or disclose the preserved response.
HA003_SCENE_ID = "into_the_deepvault:scene:ha003-i02"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MARKER_CHARS = 16384


def run_primary_only_ha003_marker_diagnostic(
    *,
    preserved_response_marker: object,
    recorded_transport_request_sha256: object,
) -> dict[str, Any]:
    """Compare one exact response marker to the hash-bound dispatched request.

    The designated primary supplies only the exact marker already isolated in
    memory and the recorded transport hash. The Study 3 request is rebuilt from
    its frozen, hash-verified inputs here. This function never accepts the raw
    response, reads no response/evidence path, and emits no marker or prose.

    A true result means exactly one canonical guarded annotation equals the
    marker and the annotation records match the hash-bound request. False means
    the verified request does not explicitly annotate that exact marker as
    guarded. Missing, mismatched, or ambiguous evidence yields a null result.
    """

    marker_sha256 = _hash_marker(preserved_response_marker)
    recorded_hash = (
        recorded_transport_request_sha256
        if type(recorded_transport_request_sha256) is str
        and _SHA256_RE.fullmatch(recorded_transport_request_sha256)
        else None
    )
    report: dict[str, Any] = {
        "scene_id": HA003_SCENE_ID,
        "result": None,
        "ambiguity_code": None,
        "hashes": {
            "response_marker_sha256": marker_sha256,
            "recorded_transport_request_sha256": recorded_hash,
            "reconstructed_transport_request_sha256": None,
            "canonical_guarded_annotations_sha256": None,
            "request_guarded_annotations_sha256": None,
        },
    }

    if preserved_response_marker is None:
        return _indeterminate(report, "RESPONSE_MARKER_MISSING")
    if marker_sha256 is None:
        return _indeterminate(report, "RESPONSE_MARKER_INVALID")
    if recorded_transport_request_sha256 is None:
        return _indeterminate(report, "TRANSPORT_REQUEST_HASH_MISSING")
    if recorded_hash is None:
        return _indeterminate(report, "TRANSPORT_REQUEST_HASH_INVALID")

    try:
        request = study3_request.build_request(HA003_SCENE_ID)
        reconstructed_hash = hashlib.sha256(
            _transport_canonical_bytes(request)
        ).hexdigest()
    except Exception:
        return _indeterminate(report, "REQUEST_RECONSTRUCTION_UNAVAILABLE")

    report["hashes"]["reconstructed_transport_request_sha256"] = (
        reconstructed_hash
    )
    if reconstructed_hash != recorded_hash:
        return _indeterminate(report, "TRANSPORT_REQUEST_HASH_MISMATCH")

    try:
        binding = study3_contract.load_scene_binding(HA003_SCENE_ID)
        canonical_rows = _guarded_annotation_rows(binding.expected_bundle)
        request_rows = _request_guarded_annotation_rows(request)
        canonical_values = _annotation_values(canonical_rows)
        binding_values = binding.guarded_markers
        if (
            type(binding_values) not in (tuple, list)
            or any(type(value) is not str for value in binding_values)
            or tuple(canonical_values) != tuple(binding_values)
        ):
            return _indeterminate(report, "CANONICAL_ANNOTATION_BINDING_INVALID")

        canonical_bytes = _transport_canonical_bytes(canonical_rows)
        request_bytes = _transport_canonical_bytes(request_rows)
    except _DiagnosticEvidenceError as error:
        return _indeterminate(report, error.code)
    except Exception:
        return _indeterminate(report, "GUARDED_ANNOTATIONS_UNAVAILABLE")

    report["hashes"]["canonical_guarded_annotations_sha256"] = hashlib.sha256(
        canonical_bytes
    ).hexdigest()
    report["hashes"]["request_guarded_annotations_sha256"] = hashlib.sha256(
        request_bytes
    ).hexdigest()

    if canonical_bytes != request_bytes:
        return _indeterminate(report, "REQUEST_GUARDED_ANNOTATIONS_MISMATCH")

    matches = [
        row["exact_value"]
        for row in canonical_rows
        if row["exact_value"] == preserved_response_marker
    ]
    if len(matches) > 1:
        return _indeterminate(report, "GUARDED_MARKER_MATCH_AMBIGUOUS")

    report["result"] = len(matches) == 1
    return report


class _DiagnosticEvidenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _hash_marker(marker: object) -> str | None:
    if type(marker) is not str or not marker or len(marker) > _MAX_MARKER_CHARS:
        return None
    try:
        return hashlib.sha256(marker.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return None


def _guarded_annotation_rows(expected_bundle: object) -> list[dict[str, Any]]:
    if not isinstance(expected_bundle, Mapping):
        raise _DiagnosticEvidenceError("CANONICAL_ANNOTATIONS_MISSING")
    protected = expected_bundle.get("protected_unknowns")
    rows = (
        protected.get("guarded_content_markers")
        if isinstance(protected, Mapping)
        else None
    )
    if type(rows) not in (list, tuple):
        raise _DiagnosticEvidenceError("CANONICAL_ANNOTATIONS_MISSING")
    plain_rows = [_to_plain(row) for row in rows]
    if any(
        type(row) is not dict or type(row.get("exact_value")) is not str
        for row in plain_rows
    ):
        raise _DiagnosticEvidenceError("CANONICAL_ANNOTATIONS_INVALID")
    return plain_rows


def _request_guarded_annotation_rows(request: object) -> list[dict[str, Any]]:
    if type(request) is not dict:
        raise _DiagnosticEvidenceError("REQUEST_SHAPE_INVALID")
    messages = request.get("messages")
    if (
        type(messages) is not list
        or len(messages) != 2
        or type(messages[1]) is not dict
        or type(messages[1].get("content")) is not str
    ):
        raise _DiagnosticEvidenceError("REQUEST_SHAPE_INVALID")

    user_message = messages[1]["content"]
    begin, end, _rule_id = study3_request._SECTION_MARKERS["expected_bundle"]
    if user_message.count(begin) != 1 or user_message.count(end) != 1:
        raise _DiagnosticEvidenceError("REQUEST_ANNOTATION_SECTION_AMBIGUOUS")
    start = user_message.index(begin) + len(begin)
    finish = user_message.index(end)
    if finish < start:
        raise _DiagnosticEvidenceError("REQUEST_ANNOTATION_SECTION_INVALID")
    section = user_message[start:finish]
    if section.startswith("\n"):
        section = section[1:]
    if section.endswith("\n"):
        section = section[:-1]
    try:
        expected_bundle = json.loads(
            section,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        raise _DiagnosticEvidenceError("REQUEST_ANNOTATIONS_INVALID") from None
    return _guarded_annotation_rows(expected_bundle)


def _annotation_values(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(row["exact_value"] for row in rows)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_non_finite(_value: str) -> None:
    raise ValueError("non-finite value")


def _to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_plain(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_to_plain(item) for item in value]
    return value


def _indeterminate(report: dict[str, Any], code: str) -> dict[str, Any]:
    report["result"] = None
    report["ambiguity_code"] = code
    return report


__all__ = ["HA003_SCENE_ID", "run_primary_only_ha003_marker_diagnostic"]
