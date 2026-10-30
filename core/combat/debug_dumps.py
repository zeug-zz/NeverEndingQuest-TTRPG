# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Debug-dump policy for combat diagnostics."""


def combat_debug_dumps_enabled() -> bool:
    """Return whether verbose combat diagnostic dumps are enabled."""
    try:
        from debug_config import DEBUG_CATEGORIES

        return bool(DEBUG_CATEGORIES.get("combat_manager_debug", False))
    except Exception:
        return False
