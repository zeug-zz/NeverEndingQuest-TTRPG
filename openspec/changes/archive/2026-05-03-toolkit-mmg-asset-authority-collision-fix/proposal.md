# Proposal: toolkit-mmg-asset-authority-collision-fix

## Problem Statement

The Module Media Generator (MMG) and description tooling currently treat some Thornwood entities as both NPC assets and MONSTER assets when the same slug appears in `npcs[]` and `monsters[]`. This is an actor-authority leak, not merely a thumbnail collision.

Concrete examples:

1. `Bandit Captain Gorvek` appears as a monster-authoritative combat/statblock actor but is also surfaced as an NPC asset row.
2. `Corrupted Ranger Thane` is correctly tracked at runtime as `entity_type: "monster"` in `data/runtime/scene_followers.json`, but stale `*_BU.json` NPC entries can still reintroduce him as an NPC asset.
3. `Malarok the Corruptor` is the module boss monster/statblock actor but stale backup NPC data can still make MMG and description lookup treat him as an NPC.

The previous delegated-media approach (`media_authority: "monster:<id>"`) masks MMG media symptoms by allowing duplicate NPC rows to pass completion. That does not fix the underlying authority model. The final behavior must keep monster-authoritative actors as monsters while preserving their ability to parley, surrender, be captured, guide the party, or become visible scene followers.

A secondary problem remains: the NPC description generation path must not import a non-existent `NPCBuilder` class from `core.generators.npc_builder`.

## Objective

1. Establish canonical monster actor authority for same-slug entities that are authored as module monsters or have module monster JSON/statblock files.
2. Suppress or ignore duplicate same-slug NPC asset rows for monster-authoritative actors in MMG unified asset and report paths.
3. Preserve narrative UX: intelligent monsters can talk, negotiate, flee, be captured, guide, or become scene followers without being reclassified as NPC assets.
4. Keep `updateSceneFollower` with `entityType: "monster"` as the durable non-combat/follower state path for monster-authoritative scene actors.
5. Fix NPC description generation so true NPCs use available description sources and AI fallback without broken imports.

## Non-Goals

- Do not regenerate AI images.
- Do not remove monster media or monster JSON/statblock authority.
- Do not make monsters auto-combat-only; monster authority is mechanical/media identity, not a forced hostility state.
- Do not change formal combat routing: combat still begins through `createEncounter.monsters[]` when a combat commitment point is reached.
- Do not broaden the v2 Titan/background-entity pipeline.

## Rollout Risk

- Moderate risk: existing source-contract tests currently assert delegated duplicate NPC rows and must be replaced.
- Low runtime gameplay risk if implementation stays in toolkit/MMG and description lookup paths, because `updateSceneFollower(entityType="monster")` already supports non-combat monster follower visibility.
- Thornwood publishability has a separate pre-existing `vitreol_corrupted_thrall` media gap; this change must not conflate that blocker with the actor-authority fix.

## Fallback Strategy

- If canonical suppression causes a toolkit regression, retain type-qualified frontend keys as a safety net while fixing backend filtering.
- If a true NPC is mistakenly suppressed, the test suite must prove the NPC is not module monster-authoritative before allowing suppression.
- Existing monster media remains authoritative and can be restored without provider calls.

## SP/MP Compatibility

Toolkit and module-authority behavior is admin/developer-facing. Runtime TABLETOP MODE benefits by keeping follower monsters coherent, and single-player behavior remains compatible because monster statblock/media identity is unchanged.
