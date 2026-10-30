# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Legacy module-identity shim for multi-PC combat synchronization."""

import sys

from core.combat.multi_pc import sync as _implementation

sys.modules[__name__] = _implementation
