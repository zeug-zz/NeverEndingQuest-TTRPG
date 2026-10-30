# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Narration - Deterministic template selection and output.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import hashlib
from typing import Any, Callable, List, Optional, Sequence

# TABLETOP MODE: Publication-boundary stops are sandbox-authorized and inert by default.
from core.combat.turn_fault_injection import maybe_inject_combat_turn_fault


def select_deterministic_template(seed_parts: Sequence[Any], templates: Sequence[str]) -> str:
    """Select a legacy narration template using the original stable hash."""
    if not templates:
        return ""
    seed = "|".join(str(part or "") for part in seed_parts)
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    return templates[digest[0] % len(templates)]


def publish_combat_narration(
    narration: str,
    *,
    applied_id: Optional[str] = None,
    emit: Callable[[str], Any],
    flush: Callable[[], Any],
) -> Optional[str]:
    """Publish narration with private receipt correlation and legacy output."""
    if applied_id is not None:
        try:
            from utils.combat_latency_trace import trace_combat_observation

            trace_combat_observation(
                "combat_turn_success_publication",
                applied_id=applied_id,
            )
        except Exception:
            # Correlation telemetry is internal and must not alter delivery.
            pass
    def emit_with_publication_boundary(text: str) -> Any:
        emit(text)
        if applied_id is not None:
            maybe_inject_combat_turn_fault("during_success_publication")

    publish_combat_output(
        f"Dungeon Master: {narration}",
        emit=emit_with_publication_boundary if applied_id is not None else emit,
        flush=flush,
    )
    if applied_id is not None:
        maybe_inject_combat_turn_fault("after_success_publication")
    return applied_id


def publish_combat_output(
    output: str,
    *,
    emit: Callable[[str], Any],
    flush: Callable[[], Any],
) -> None:
    """Emit one legacy combat output line and flush immediately."""
    emit(output)
    flush()
