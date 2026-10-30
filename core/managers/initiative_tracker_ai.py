# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Legacy module-identity shim for the combat-only initiative tracker."""

import sys

from core.combat import initiative_tracker_ai as _implementation

sys.modules[__name__] = _implementation
