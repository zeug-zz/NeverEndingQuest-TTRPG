## Why

The unified-assets MMG endpoint recently added `creatures` and `visibleHostiles` as monster extraction sources alongside the existing structured `location.monsters` path. This improves discovery for modules that put combatants in those fields, but it also creates an authority problem: `creatures` prose often contains authored NPCs with role qualifiers, such as `Ma (commoner)`, `Blarg (half-orc)`, and `Red (The Crimson Binder)`. These are not independent monster assets.

The current endpoint patch is too broad because it can promote every extracted monster candidate into monster authority before resolving NPC conflicts. That can make weak `creatures` tokens suppress true NPC rows, which is the inverse of the desired behavior. The plan must be refined so MMG distinguishes explicit module monster authority from weak creature-derived candidates.

## What Changes

- **Source-aware authority resolution**: Track where each monster candidate came from: module monster JSON, structured `location.monsters`, `location.creatures`, or `location.visibleHostiles`.
- **Module-local authority only**: Build MMG authority from the target module's files only. Do not use runtime campaign state such as `party_tracker.json` when deciding toolkit asset authority.
- **Explicit monster authority wins**: If a slug has a module monster JSON file or appears in structured `location.monsters`, it remains a monster asset even if stale NPC hint data exists for the same slug.
- **NPC authority wins over weak candidates**: If a slug is authored as an NPC and appears only through weak monster sources (`creatures` or `visibleHostiles`), keep the NPC row and drop the weak monster candidate.
- **Authored NPC identity set**: Build from module-local sources including `module_context.json -> npcs`, `module_context_BU.json -> npcs` when present, area `location.npcs[].name`, and normalized alias forms. Parenthetical and comma/appositive labels SHOULD contribute bare-prefix aliases so `Ma (Margaret Thornfield)` can match `Ma (commoner)`.
- **Report parity**: MMG report canonicalization must use the same authority decision as the unified-assets endpoint. It must not globally prefer monster rows for every same-slug collision.
- **No full revert**: Keep `creatures` and `visibleHostiles` extraction, but refine conflict resolution so it respects module-local actor authority.

## Capabilities

### New Capabilities

- `mmg-creature-to-npc-authority-resolution`: Deterministic source-aware resolution for MMG assets discovered from `creatures` and `visibleHostiles`, with module-local NPC and monster authority sets.

### Modified Capabilities

- `toolkit-mmg-duplicate-authority-preference`: Same-slug monster preference applies only when the slug is explicitly module monster-authoritative, not merely because a weak creature-derived candidate was extracted.

## Impact

- **Affected code**: `web/web_interface.py` unified-assets endpoint, `utils/module_media_generator_report.py`, and likely a small shared helper for module-local MMG authority decisions.
- **Affected modules**: Modules using `creatures` or `visibleHostiles` for mixed NPC/monster scene data, especially `Night_of_the_Restless_Dead`; monster-authoritative modules such as `The_Thornwood_Watch` must keep their existing behavior.
- **Backward compatible**: Structured `location.monsters` remains authoritative for monster assets. True NPCs remain NPC assets.
- **Module independence**: Toolkit asset authority must not vary based on currently loaded party/campaign runtime state.
- **SP/MP compatibility**: No gameplay runtime change. The unified-assets endpoint is toolkit-only.
- **Rollout risk**: Medium. The behavior touches two existing authority models that can conflict. Regression tests must cover both Night-style weak creature NPCs and Thornwood-style monster-authoritative actors.
