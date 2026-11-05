# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Fixed public assets for the unauthenticated player login shell."""

from __future__ import annotations

from types import MappingProxyType

PUBLIC_LOGIN_ASSETS = MappingProxyType(
    {
        "shell.css": (
            b"text/css; charset=utf-8",
            b"body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:36rem;"
            b"padding:0 1rem}main{border:1px solid #888;border-radius:.5rem;padding:1.5rem}"
            b"label,input,button{display:block;margin:.75rem 0}input,button{font:inherit}",
        )
    }
)
