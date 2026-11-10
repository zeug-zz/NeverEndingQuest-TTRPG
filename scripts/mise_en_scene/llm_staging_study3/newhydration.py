# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 3 in-memory adapter to the unchanged full-output safety gates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from ..llm_staging.output_gates import OutputDiagnostic, OutputGateReport
from ..llm_staging_study2 import hydration as study2_hydration
from .contract import ContractError, validate_delta_payload
from .protocol import SCENE_ORDER


MAX_REPORT_DIAGNOSTICS = 128
MAX_GATE_OUTPUT_BYTES = 2 * 1024 * 1024
_FIXTURE_LABEL = "HAND_ASSEMBLED_DETERMINISTIC_SOFTWARE_FIXTURE_ONLY"
_LEGACY_METADATA_NOTE = (
    "REQUIRED_BY_UNCHANGED_GATE_ENVELOPE_ONLY_NOT_MODEL_TEST_EVIDENCE"
)


@dataclass(frozen=True)
class ContractDiagnostic:
    """Strict Study 3 contract failure with bounded metadata only."""

    code: str
    rule_id: str
    path: str


@dataclass(frozen=True)
class NotEvaluatedStage:
    """A stage that did not run because a named prerequisite was unavailable."""

    stage: str
    dependency: str
    reason_code: str


@dataclass(frozen=True)
class Study3OutputGateReport:
    """Provider-free hydration/gate outcome; no prose or quality verdicts."""

    scene_id: str
    delta_artifact_sha256: str | None
    hydrated_output_sha256: str | None
    contract_status: str
    hydration_status: str
    downstream_status: str
    contract_diagnostics: tuple[ContractDiagnostic, ...] = ()
    downstream_diagnostics: tuple[OutputDiagnostic, ...] = ()
    not_evaluated: tuple[NotEvaluatedStage, ...] = ()
    legacy_llm_builder_tested_metadata: bool | None = None

    @property
    def deterministic_status(self) -> str:
        statuses = (
            self.contract_status,
            self.hydration_status,
            self.downstream_status,
        )
        if "FAIL" in statuses:
            return "FAIL"
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if "NOT_EVALUATED" in statuses:
            return "NOT_EVALUATED"
        return "PASS"

    def to_dict(self) -> dict[str, Any]:
        """Return bounded diagnostics without request or response content."""

        return {
            "schema": "neq.llm_staging_study3_output_gate_report.v1",
            "scene_id": self.scene_id,
            "delta_artifact_sha256": self.delta_artifact_sha256,
            "hydrated_output_sha256": self.hydrated_output_sha256,
            "deterministic_status": self.deterministic_status,
            "stages": {
                "study3_contract": {
                    "status": self.contract_status,
                    "diagnostics": [
                        {
                            "code": item.code,
                            "rule_id": item.rule_id,
                            "path": item.path,
                        }
                        for item in self.contract_diagnostics[:MAX_REPORT_DIAGNOSTICS]
                    ],
                },
                "in_memory_hydration": {"status": self.hydration_status},
                "full_unchanged_safety_gates": {
                    "status": self.downstream_status,
                    "diagnostics": [
                        {
                            "code": item.code,
                            "layer": item.layer,
                            "path": item.path,
                        }
                        for item in self.downstream_diagnostics[:MAX_REPORT_DIAGNOSTICS]
                    ],
                },
            },
            "not_evaluated": [
                {
                    "stage": item.stage,
                    "status": "NOT_EVALUATED",
                    "dependency": item.dependency,
                    "reason_code": item.reason_code,
                }
                for item in self.not_evaluated[:MAX_REPORT_DIAGNOSTICS]
            ],
            "reference_evidence": {
                "classification": _FIXTURE_LABEL,
                "semantic_review_status": "PENDING",
                "owner_rating_status": "PENDING",
                "model_capability_verdict": "PENDING",
                "software_preparation_readiness": "PENDING",
                "legacy_llm_builder_tested_metadata": self.legacy_llm_builder_tested_metadata,
                "legacy_metadata_interpretation": _LEGACY_METADATA_NOTE,
            },
        }


@dataclass(frozen=True)
class _DownstreamEvaluation:
    status: str
    hydrated_output_sha256: str | None
    diagnostics: tuple[OutputDiagnostic, ...]
    not_evaluated_dependency: str | None = None
    reason_code: str | None = None


def hydrate_delta_output(output_bytes: object, *, scene_id: str) -> dict[str, Any]:
    """Validate a Study 3 delta and adapt it to a fresh full fixture in memory."""

    validated = validate_delta_payload(output_bytes, scene_id=scene_id)
    canonical = study2_hydration._load_canonical_inputs(scene_id)
    return study2_hydration._hydrate_validated_delta(validated, canonical)


def validate_delta_output(
    output_bytes: object, *, scene_id: str
) -> Study3OutputGateReport:
    """Run the strict Study 3 contract, in-memory hydration, and old gate chain."""

    delta_hash = _bounded_delta_hash(output_bytes)
    safe_scene_id = scene_id if type(scene_id) is str and scene_id in SCENE_ORDER else ""

    try:
        validated = validate_delta_payload(output_bytes, scene_id=scene_id)
    except ContractError as error:
        contract_status = "BLOCKED" if error.rule_id.startswith("HOST-") else "FAIL"
        return Study3OutputGateReport(
            scene_id=safe_scene_id,
            delta_artifact_sha256=delta_hash,
            hydrated_output_sha256=None,
            contract_status=contract_status,
            hydration_status="NOT_EVALUATED",
            downstream_status="NOT_EVALUATED",
            contract_diagnostics=(
                ContractDiagnostic(error.code, error.rule_id, error.path),
            ),
            not_evaluated=(
                NotEvaluatedStage(
                    "in_memory_hydration", "study3_contract", error.code
                ),
                NotEvaluatedStage(
                    "full_unchanged_safety_gates", "study3_contract", error.code
                ),
            ),
        )

    try:
        canonical = study2_hydration._load_canonical_inputs(scene_id)
    except study2_hydration.ContractError as error:
        return _not_evaluated_canonical(safe_scene_id, delta_hash, error.code)
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError):
        return _not_evaluated_canonical(
            safe_scene_id, delta_hash, "CANONICAL_INPUT_SHAPE_INVALID"
        )

    try:
        full_output = study2_hydration._hydrate_validated_delta(validated, canonical)
    except study2_hydration.ContractError as error:
        return Study3OutputGateReport(
            scene_id=safe_scene_id,
            delta_artifact_sha256=delta_hash,
            hydrated_output_sha256=None,
            contract_status="PASS",
            hydration_status="FAIL",
            downstream_status="NOT_EVALUATED",
            downstream_diagnostics=(
                OutputDiagnostic(error.code, "hydration", "$output"),
            ),
            not_evaluated=(
                NotEvaluatedStage(
                    "full_unchanged_safety_gates", "in_memory_hydration", error.code
                ),
            ),
        )
    except (KeyError, TypeError, ValueError, IndexError, RecursionError):
        return Study3OutputGateReport(
            scene_id=safe_scene_id,
            delta_artifact_sha256=delta_hash,
            hydrated_output_sha256=None,
            contract_status="PASS",
            hydration_status="FAIL",
            downstream_status="NOT_EVALUATED",
            downstream_diagnostics=(
                OutputDiagnostic("HYDRATION_SHAPE_INVALID", "hydration", "$output"),
            ),
            not_evaluated=(
                NotEvaluatedStage(
                    "full_unchanged_safety_gates",
                    "in_memory_hydration",
                    "HYDRATION_SHAPE_INVALID",
                ),
            ),
        )

    evaluation = _validate_hydrated_output(full_output, canonical, scene_id)
    not_evaluated: tuple[NotEvaluatedStage, ...] = ()
    if evaluation.status == "NOT_EVALUATED":
        not_evaluated = (
            NotEvaluatedStage(
                "full_unchanged_safety_gates",
                evaluation.not_evaluated_dependency or "hydrated_output",
                evaluation.reason_code or "DOWNSTREAM_GATE_NOT_EVALUATED",
            ),
        )
    return Study3OutputGateReport(
        scene_id=safe_scene_id,
        delta_artifact_sha256=delta_hash,
        hydrated_output_sha256=evaluation.hydrated_output_sha256,
        contract_status="PASS",
        hydration_status="PASS",
        downstream_status=evaluation.status,
        downstream_diagnostics=evaluation.diagnostics,
        not_evaluated=not_evaluated,
        legacy_llm_builder_tested_metadata=True,
    )


def _validate_hydrated_output(
    full_output: object,
    canonical: study2_hydration.CanonicalSceneInputs,
    scene_id: str,
) -> _DownstreamEvaluation:
    """Run the unchanged Study 1 validator on a hydrated in-memory value."""

    try:
        output_bytes = _canonical_json_bytes(full_output)
        if len(output_bytes) > MAX_GATE_OUTPUT_BYTES:
            return _downstream_not_evaluated(
                None, "HYDRATED_OUTPUT_BYTE_LIMIT", "hydrated_output"
            )
        expected_inputs = canonical.expected_inputs_copy()
        schema = canonical.output_schema_copy()
    except study2_hydration.ContractError as error:
        return _downstream_not_evaluated(
            None, error.code, "study1_canonical_gate_inputs"
        )
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        return _downstream_not_evaluated(
            None, "DOWNSTREAM_INPUT_SHAPE_INVALID", "study1_canonical_gate_inputs"
        )

    output_hash = hashlib.sha256(output_bytes).hexdigest()
    try:
        gate_report: OutputGateReport = study2_hydration.validate_model_output(
            output_bytes, expected_inputs, scene_id, schema
        )
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, RecursionError):
        return _downstream_not_evaluated(
            output_hash, "DOWNSTREAM_GATE_SHAPE_INVALID", "unchanged_output_gate_chain"
        )
    return _DownstreamEvaluation(
        status=gate_report.deterministic_status,
        hydrated_output_sha256=gate_report.artifact_sha256 or output_hash,
        diagnostics=tuple(gate_report.diagnostics[:MAX_REPORT_DIAGNOSTICS]),
    )


def _not_evaluated_canonical(
    scene_id: str, delta_hash: str | None, reason_code: str
) -> Study3OutputGateReport:
    return Study3OutputGateReport(
        scene_id=scene_id,
        delta_artifact_sha256=delta_hash,
        hydrated_output_sha256=None,
        contract_status="PASS",
        hydration_status="NOT_EVALUATED",
        downstream_status="NOT_EVALUATED",
        not_evaluated=(
            NotEvaluatedStage(
                "in_memory_hydration", "study1_canonical_inputs", reason_code
            ),
            NotEvaluatedStage(
                "full_unchanged_safety_gates", "in_memory_hydration", reason_code
            ),
        ),
    )


def _downstream_not_evaluated(
    output_hash: str | None, reason_code: str, dependency: str
) -> _DownstreamEvaluation:
    return _DownstreamEvaluation(
        status="NOT_EVALUATED",
        hydrated_output_sha256=output_hash,
        diagnostics=(
            OutputDiagnostic("DOWNSTREAM_GATE_NOT_EVALUATED", "dependency", "$output"),
        ),
        not_evaluated_dependency=dependency,
        reason_code=reason_code,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _bounded_delta_hash(value: object) -> str | None:
    if type(value) is not bytes or len(value) > study2_hydration.MAX_DELTA_BYTES:
        return None
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "ContractDiagnostic",
    "NotEvaluatedStage",
    "Study3OutputGateReport",
    "hydrate_delta_output",
    "validate_delta_output",
]
