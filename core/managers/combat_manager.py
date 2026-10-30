# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Compatibility shim for the package-owned combat manager.

The module alias is deliberate: old-path imports and monkeypatches must act on
the package-owned module globals rather than on copied wrapper attributes.
"""

# TABLETOP MODE: Keep the legacy import path as the single module identity.
import sys

from core.combat import combat_manager as _implementation

sys.modules[__name__] = _implementation
