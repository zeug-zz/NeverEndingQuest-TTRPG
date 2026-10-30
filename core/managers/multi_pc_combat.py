# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Legacy module-identity shim for package-owned multi-PC combat."""

import sys

from core.combat.multi_pc import manager as _implementation

# Preserve old-path imports and monkeypatches as the same mutable module.
sys.modules[__name__] = _implementation
