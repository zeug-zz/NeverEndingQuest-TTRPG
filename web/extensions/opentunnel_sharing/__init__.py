# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""OpenTunnel sharing companion resolution and lifecycle boundaries."""

from .companion import (
    CompanionResolution,
    resolve_companion,
    verify_companion_digest,
)

__all__ = [
    "CompanionResolution",
    "resolve_companion",
    "verify_companion_digest",
]
