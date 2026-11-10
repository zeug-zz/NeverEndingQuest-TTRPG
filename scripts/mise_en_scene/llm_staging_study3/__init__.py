# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3 protocol definitions."""

from .contract import (
    ContractError,
    HOST_RULE_MAP,
    OUTPUT_RULE_MAP,
    audit_rule_parity,
    load_scene_binding,
    rule_inventory,
    validate_delta_payload,
)
from .protocol import (
    MODEL_ID,
    SCENE_ORDER,
    STUDY_ID,
    load_input_bindings,
    render_output_schema,
    render_output_schema_json,
    render_system_prompt,
)
from .diagnostics import (
    DIAGNOSTIC_LABEL,
    diagnose_delta_bytes,
    run_study2_collect_all,
)
from .newrequest import (
    RequestBuildError,
    RequestParityError,
    audit_request_parity,
    build_request,
    request_transport_metadata,
)
from .newhydration import (
    ContractDiagnostic,
    NotEvaluatedStage,
    Study3OutputGateReport,
    hydrate_delta_output,
    validate_delta_output,
)
from .sizing import (
    SizingBlocked,
    build_sizing_report,
    future_host_preflight,
    validate_actual_cost_accounting,
)
from .preflight import (
    ApprovalPins,
    DispatchPins,
    OutcomeDecision,
    PreflightBlocked,
    PreflightDecision,
    ProviderIdentity,
    SyntheticLedgerSnapshot,
    classify_attempt_outcome,
    synthetic_preflight,
)

__all__ = [
    "ContractError",
    "ContractDiagnostic",
    "DIAGNOSTIC_LABEL",
    "ApprovalPins",
    "DispatchPins",
    "HOST_RULE_MAP",
    "MODEL_ID",
    "NotEvaluatedStage",
    "OutcomeDecision",
    "OUTPUT_RULE_MAP",
    "PreflightBlocked",
    "PreflightDecision",
    "ProviderIdentity",
    "RequestBuildError",
    "RequestParityError",
    "SCENE_ORDER",
    "STUDY_ID",
    "Study3OutputGateReport",
    "SizingBlocked",
    "SyntheticLedgerSnapshot",
    "audit_rule_parity",
    "audit_request_parity",
    "build_request",
    "build_sizing_report",
    "classify_attempt_outcome",
    "diagnose_delta_bytes",
    "load_scene_binding",
    "load_input_bindings",
    "hydrate_delta_output",
    "future_host_preflight",
    "render_output_schema",
    "render_output_schema_json",
    "render_system_prompt",
    "rule_inventory",
    "request_transport_metadata",
    "run_study2_collect_all",
    "synthetic_preflight",
    "validate_delta_payload",
    "validate_delta_output",
    "validate_actual_cost_accounting",
]
