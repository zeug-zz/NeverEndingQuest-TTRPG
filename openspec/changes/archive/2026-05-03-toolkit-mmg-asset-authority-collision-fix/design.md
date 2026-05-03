# Design: toolkit-mmg-asset-authority-collision-fix

## Architecture Boundaries

### Contract Layer (MUST)

The implementation MUST separate actor authority from narrative interaction state.

- Module `monsters[]`, module monster JSON files, and `media/monsters/` files are the authoritative statblock/media identity for same-slug monster actors.
- Module `npcs[]` entries with the same canonical slug as an authoritative module monster are descriptive/dialogue hints only for that actor. They MUST NOT create independent MMG NPC assets.
- `updateSceneFollower` records with `entityType: "monster"` are the durable non-combat state path for captured, parleying, guiding, or temporarily allied monster-authoritative actors.
- Formal combat remains routed through `createEncounter.monsters[]` when a combat commitment point occurs.
- True NPCs that are not module monster-authoritative remain normal NPC assets and keep NPC description/media behavior.

### Guidance Layer (SHOULD)

- Keep the frontend `type:id` qualified key helper because it prevents future cross-type UI collisions and is harmless even when duplicate same-slug rows are suppressed.
- Prefer backend canonical filtering over frontend hiding so reports, generation, and tests all observe the same source of truth.
- Prefer a small helper that answers "is this slug module monster-authoritative?" using `build_module_monster_authority()` and module monster JSON files.

## Authority Model

### Monster-Authoritative Actor

A slug is monster-authoritative when it appears in any of these sources:

1. `modules/<module>/monsters/<slug>.json`
2. Structured `monsters[]` entries in live area files
3. Structured `monsters[]` entries in canonical backup area files when live files are absent or the backup is the scan source
4. `build_module_monster_authority(<module>)`

When a monster-authoritative slug also appears in `npcs[]`, MMG SHALL keep the monster asset row and suppress the NPC asset row.

### Descriptive NPC Hint

A same-slug `npcs[]` entry for a monster-authoritative slug may still provide:

- personality or attitude guidance,
- parley/capture setup,
- authored visual description text,
- module context for scene-follower state.

It MUST NOT create a separate NPC media obligation or NPC compendium classification.

### True NPC Asset

A slug remains a true NPC asset when it appears only in NPC authority sources and is not module monster-authoritative. Examples include `Wounded Ranger Gareth` and `Merchant Kael`.

## Key Decisions

1. The previous delegated duplicate row model is transitional only. Final MMG completion SHOULD NOT require `authority_delegated` NPC audit rows for Gorvek, Thane, or Malarok.
2. `media_authority` metadata may remain temporarily for compatibility, but duplicate same-slug NPC rows are not the acceptance target.
3. NPC description resolution must not use `npc_compendium.json` to classify monster-authoritative slugs as NPC assets.
4. Monster parley/capture/follower UX is preserved by prompt contracts and runtime scene follower state, not by duplicating monsters into NPC asset rows.

## Data Remediation

Thornwood should be remediated so:

- `Bandit Captain Gorvek`, `Corrupted Ranger Thane`, and `Malarok the Corruptor` are represented as monster-authoritative assets in MMG.
- Their same-slug NPC compendium entries are removed or ignored by MMG/description lookup when module monster authority is present.
- Thornwood's MMG report has no duplicate NPC audit rows for those slugs.
- The pre-existing `vitreol_corrupted_thrall` media blocker remains reported separately by publishability tooling.

## Migration

- No schema migration required.
- Existing runtime `scene_followers.json` records with `entity_type: "monster"` remain valid.
- Existing monster media and monster JSON files remain authoritative.
- Existing true NPC descriptions remain valid.

## Rollback

- Re-enable duplicate row emission only as a temporary diagnostic fallback if canonical filtering breaks true NPC assets.
- Keep monster media/statblock files untouched so rollback does not require provider calls.
