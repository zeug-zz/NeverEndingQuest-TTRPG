# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Render deterministic M1 sketches from filtered mapping projections."""

from __future__ import annotations

from collections.abc import Mapping, Set as AbstractSet
from typing import Any, Optional

from scripts.mapping_pilot.knowledge import filter_layout_for_viewpoint
from scripts.mapping_pilot.layout import validate_layout
from scripts.mapping_pilot.projections import render_schematic


def render_m1_sketch(
    layout: Mapping[str, Any],
    *,
    current_location_id: str,
    active_actor_id: str,
    party_known_ids: AbstractSet[str],
    perceived_ids: Optional[AbstractSet[str]] = None,
) -> str:
    """Validate, filter, and render a schematic without inferring spatial facts."""
    validated = validate_layout(layout)
    projection = filter_layout_for_viewpoint(
        validated,
        current_location_id=current_location_id,
        active_actor_id=active_actor_id,
        party_known_ids=party_known_ids,
        perceived_ids=perceived_ids,
    )
    sketch = render_schematic(projection)
    try:
        sketch.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("M1 sketch must contain ASCII text") from exc
    return sketch
