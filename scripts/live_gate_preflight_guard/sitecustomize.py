# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Dedicated interpreter-startup entry point for live-gate preflight."""

from scripts.sitecustomize import activate_preflight_guard


activate_preflight_guard()
