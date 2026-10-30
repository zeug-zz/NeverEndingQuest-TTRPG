# ADR-0032: Single Tabletop Runtime (Minimum Party Is One PC)

- Date: 2026-09-21
- Status: Accepted
- Supersedes: ADR-0004
- Superseded by: None

## Context

ADR-0031 retired upstream merge parity, which removed the remaining motive for
tracking a separate single-player mode as a compatibility target. The shipped
runtime already behaves as one tabletop runtime:

- `config.py` sets `MULTIPLAYER_MODE = True` ("Enable tabletop/multi-PC UI even
  with 1 character").
- `MultiPCCombatManager.is_enabled()` returns `MULTIPLAYER_MODE`, not a party
  size check, and `create_combat_manager()` has no party-size check.
- `web/web_interface.py` already exposes a one-PC tabletop recovery path that
  treats a single PC as a tabletop party.

The remaining `len(party_members) > 1` branches are migration debt from the
phased roadmap in ADR-0004, not evidence of a second runtime mode.

## Decision

- There is exactly one runtime mode: the tabletop runtime, with 1..x PCs plus
  NPCs. A one-PC party is the minimum tabletop party, not a separate mode.
- "Single-player" is retired as product terminology and as a compatibility
  target. Forward-looking guidance, specs, fixtures, and gates use "1-PC party"
  wording instead.
- The 1-PC party is the regression floor for every change; a 4-PC multi-party
  remains the primary test shape.
- `MULTIPLAYER_MODE` and party-size dual-checks are migration debt. They are
  removed by a dedicated future change (working name
  `tt-single-runtime-unification`) after the router/combat workstreams land -
  never by drive-by edits.
- The scale-out path is mid-session PC addition (Manage Party) and NPC->PC
  promotion per ADR-0018.

## Consequences

- Terminology changes are required across AGENTS.md, plans, fixtures, and
  gates; this ADR declares direction and mandates no behavior change by itself.
- Compatibility gates are restated as 1-PC party smoke checks, replacing
  single-player mode coverage.
- The deferred cleanup inventory below is listed and owned by the dedicated
  unification change, not by opportunistic edits.

## Deferred Cleanup Inventory

As of 2026-09-21, each entry is a `len(party_members) > 1` gate to retire:

- `core/ai/action_handler.py:1334` - `_is_tabletop_multi_pc_guard_active()`
- `core/generators/combat_builder.py:342` - party member inclusion in
  `generate_encounter()`
- `utils/pc_manager.py:124` - `should_use_abstraction_layer()`
- `utils/compression/multi_pc_conversation_compressor.py:609` -
  `should_use_multi_pc_compression()`
- `main.py:7406` - `active_pc` tagging gate in `main_game_loop()`
- `main.py:8044` - multi-PC DM Note selection in `main_game_loop()`
- `main.py:8124` - `is_multi_pc_mode` dual-check in `main_game_loop()`
- `main.py:8175` - message tagging gate in `main_game_loop()`

## Sources

- `adrs/0004-multiplayer-activation-and-unification-roadmap.md`
- `adrs/0018-identity-first-role-lifecycle-continuity.md`
- `adrs/0031-independent-development-fork.md`
- `docs/architecture/plugin-runtime-roadmap.md` (pointer; this ADR is authoritative)
- `config.py` (`MULTIPLAYER_MODE = True`, "even with 1 character")
- `core/managers/multi_pc_combat.py` (`is_enabled()`, `create_combat_manager()`)
- `web/web_interface.py` (one-PC tabletop recovery path)
