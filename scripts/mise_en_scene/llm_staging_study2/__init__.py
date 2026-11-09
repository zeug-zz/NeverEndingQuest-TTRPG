# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Isolated Study 2 delta validation and guarded execution preparation."""

from .client import (
    ApprovalPins,
    Study2AttemptReceipt,
    Study2Client,
    Study2ExecutionError,
    Study2TransportResult,
)

from .contract import (
    ContractError,
    FrozenReference,
    FrozenSceneBinding,
    load_frozen_bindings,
    validate_delta_payload,
)
from .hydration import (
    CanonicalSceneInputs,
    Study2OutputGateReport,
    hydrate_delta_output,
    validate_delta_output,
)

__all__ = [
    "ApprovalPins",
    "CanonicalSceneInputs",
    "ContractError",
    "FrozenReference",
    "FrozenSceneBinding",
    "Study2AttemptReceipt",
    "Study2Client",
    "Study2ExecutionError",
    "Study2OutputGateReport",
    "Study2TransportResult",
    "hydrate_delta_output",
    "load_frozen_bindings",
    "validate_delta_payload",
    "validate_delta_output",
]
