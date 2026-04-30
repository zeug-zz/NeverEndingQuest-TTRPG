# updateSceneFollower Concept Plan

Status: Draft for review

## Problem

The non-combat top thumbnail strip can already render current party members, allied NPCs, current-location NPCs, and explicitly declared visible hostile presences. It does not reliably render transient narrated actors such as captives, guarded guides, parleying enemies, or monsters temporarily traveling with the party.

The current Thane case exposes the gap:

- Corrupted Ranger Thane has valid monster data and media.
- Runtime/module text records that he was captured, restrained, and became a guarded guide.
- The party has moved to `NC02` with Thane narrated as present.
- Thane is not a party NPC, not a current-location NPC, and not listed in `NC02.visibleHostiles` or equivalent metadata.
- The thumbnail strip therefore has no authoritative source from which to show his artwork.

The missing piece is not frontend rendering. The missing piece is a Python-authoritative runtime roster for scene actors who are currently present because play established them.

The related Sylara case exposes a second identity-lifecycle gap:

- The module-authored NPC is `Thorn-Touched Dryad Sylara` at `NC02`.
- The player successfully recruited her as an allied NPC.
- `party_tracker.json` now lists `Dryad Sylara` as a party NPC.
- The authored current-location NPC `Thorn-Touched Dryad Sylara` remains in the location NPC queue.
- The allied NPC portrait path then generated or selected `dryad_sylara` media, while the authored location NPC still has separate `thorn_touched_dryad_sylara` media.
- The UI therefore shows "dryad twins": one allied `Dryad Sylara`, one still-present `Thorn-Touched Dryad Sylara`.

This is related to the Thane problem at the scene-actor lifecycle layer, but it has a different immediate root cause. Thane disappeared because no durable follower/visible-scene roster represented him. Sylara duplicated because recruitment collapsed a module-authored NPC identity into an older persistent character-file identity, then the top strip could not dedupe the recruited party NPC against the original location NPC.

## Sylara Recruitment Identity Finding

The current recruitment path can let prior-session character data override module-authored NPC identity.

Observed mechanics:

- Existing file: `characters/dryad_sylara.json` with display name `Dryad Sylara`.
- Current module NPC: `Thorn-Touched Dryad Sylara` from `modules/The_Thornwood_Watch/areas/NCW001.json`.
- The recruitment action used the authored module NPC name.
- `core/ai/action_handler.py` `update_party_npcs()` calls `find_character_file_fuzzy(npc["name"])`.
- `find_character_file_fuzzy()` can match `Thorn-Touched Dryad Sylara` to `dryad_sylara.json` because `dryad sylara` is a strong subset match.
- After loading that file, `update_party_npcs()` overwrites the party NPC display name with `npc_data["name"]`, producing `Dryad Sylara` in `party_tracker.json`.
- The party strip then sees `Dryad Sylara` and `Thorn-Touched Dryad Sylara` as different normalized names and renders both.

This is partly session crosstalk because old `Dryad Sylara` data existed from earlier play, but it is also a fundamental recruitment canonicalization bug. Any module NPC with a name overlapping an older character file can be renamed this way.

The fix should preserve module-authored identity during recruitment. If an existing character file is useful for stats, media, or continuity, it should be linked as metadata rather than allowed to rename the recruited actor.

## Principle

Python enforces reality; the LLM interprets it.

The LLM DM should have broad authority to drive the narrative, including turning enemies into prisoners, guides, escorts, parley actors, temporary threats, or later combatants. That authority should become durable runtime state only after it passes through structured actions or validated state transitions.

The system should not scrape conversation prose on every render and infer current actors from raw narration. Prose is too fuzzy and can resurrect stale actors.

## Proposed Contract

Introduce a narrow structured action conceptually named `updateSceneFollower`.

Example payload:

```json
{
  "action": "updateSceneFollower",
  "parameters": {
    "entity": "Corrupted Ranger Thane",
    "entityType": "monster",
    "state": "following",
    "disposition": "guarded_guide",
    "currentLocation": "NC02",
    "visibleInStrip": true
  }
}
```

Python validates the request, writes or updates `data/runtime/scene_followers.json`, and the party-strip socket consumes that state.

## Follower Record Shape

The existing `utils/scene_follower_state.py` store uses:

```json
{
  "followers": [
    {
      "entity_id": "corrupted_ranger_thane",
      "current_location": "NC02",
      "since_turn": "..."
    }
  ]
}
```

Extend this additively, preserving compatibility with minimal existing records:

```json
{
  "entity_id": "corrupted_ranger_thane",
  "current_location": "NC02",
  "since_turn": "...",
  "display_name": "Corrupted Ranger Thane",
  "entity_type": "monster",
  "monster_type": "Corrupted Ranger Thane",
  "disposition": "guarded_guide",
  "visible_in_strip": true
}
```

Suggested optional fields:

- `display_name`: user-facing name for UI and narration.
- `entity_type`: small enum such as `monster`, `npc`, `scene_entity`.
- `monster_type`: media/stat identity for monster artwork lookup.
- `disposition`: small enum such as `guarded_captive`, `guarded_guide`, `parleying`, `hostile`, `neutral`, `escort`.
- `visible_in_strip`: explicit UI visibility bit.
- `source_module`: module that authored the entity, when known.
- `source_npc_name`: canonical module NPC name, when recruited or moved from a module location.
- `source_entity_slug`: stable module/entity slug for dedupe and media lookup.
- `character_file_ref`: optional existing character file used for stats or continuity without replacing canonical display identity.
- `recruited_from_location_id`: location id where a party-NPC transition consumed the scene actor.

## Validation Rules

Python should accept a scene-follower update only when the entity is grounded in authoritative state.

Valid grounding sources may include:

- module monster file or bestiary entry;
- module NPC roster or current/previous location NPC list;
- explicit scene authority metadata;
- recent validated encounter outcome;
- validated plot/location update that establishes escort, capture, release, or travel;
- existing follower record.

Python should reject or ignore updates when:

- the entity cannot be resolved;
- the target location is not canonical;
- the actor is already a PC or party NPC unless this is an intentional role transition;
- a fuzzy character-file match would replace a module-authored canonical NPC name;
- the requested state contradicts dead/defeated status;
- the requested state contradicts active combat ownership;
- the disposition is outside the allowed enum.

## State Transitions

Supported states should be explicit and removable. Avoid write-only follower records that can linger forever.

Suggested states:

- `following`: actor travels with or near the party.
- `present`: actor is in the current scene but not necessarily traveling.
- `held`: captive or restrained actor under party control.
- `parleying`: hostile or uncertain actor engaged in negotiation.
- `hidden`: no longer visible in strip but still tracked.
- `released`: remove from active strip and mark no longer following.
- `escaped`: remove from active strip and optionally update location.
- `dead`: remove or mark not visible, depending on future corpse/aftermath needs.
- `joined_party`: remove follower record and route through party NPC/PC lifecycle.
- `combat_started`: remove or convert into encounter combatant ownership.

Recruitment should be treated as a first-class lifecycle transition, not merely as appending a display name to `partyNPCs`:

```text
location_present -> party_npc/allied
```

When this transition occurs, the system should preserve source identity metadata and consume or suppress the original location-scene anchor. This prevents the same authored NPC from rendering once as an ally and once as a still-present location NPC.

For transient hostile/monster actors, the analogous transition is:

```text
location_present -> follower/captive/guarded_guide
```

Both cases should use the same scene actor lifecycle model.

## Thumbnail Integration

The frontend already renders `location_hostiles` outside combat using monster media paths. The minimal thumbnail fix is backend-only:

1. Build explicit visible hostiles from current location metadata as today.
2. Load scene follower records.
3. Include current-location follower records marked `visible_in_strip` and typed as monster/hostile scene actors.
4. Emit them through existing `location_hostiles` with monster media metadata.
5. Dedupe against PCs, party NPCs, current location NPCs, and explicit visible hostiles.

For Thane, the emitted shape should conceptually be:

```json
{
  "name": "Corrupted Ranger Thane",
  "type": "location_hostile",
  "monsterType": "Corrupted Ranger Thane",
  "disposition": "guarded_guide",
  "image_slug": "corrupted_ranger_thane",
  "image_version": 123456789
}
```

Optional frontend polish can display `Guarded Guide`, `Captive`, or `Parleying` instead of the current generic `Hostile Presence` tooltip.

For recruited NPCs, the same backend identity metadata should let the party strip suppress a current-location NPC when it has already become a party NPC. The dedupe should compare stable source identity fields such as `source_npc_name` or `source_entity_slug`, not just display-name strings.

## Why Not Render Generic Location Monsters?

Generic `location.monsters` can contain encounter seeds, hidden threats, or possible inhabitants. Rendering them would leak information and show actors that are not necessarily present.

The strip should show actors that are currently scene-visible or party-adjacent, not every possible monster in a location.

## Why Not Scrape Conversation History?

Conversation history is useful context for the LLM, but it is not a safe source of UI reality.

Problems with render-time prose inference:

- stale mentions can resurrect actors;
- negated mentions are hard to distinguish from presence;
- flavor text can become false mechanical state;
- compression can blur timing and location;
- every render would become an implicit state mutation risk.

Use structured actions and validated runtime hooks instead.

## Implementation Phases

### Phase 1: Consume Existing Follower State

- Extend follower record validation to allow optional metadata.
- Add a socket helper that merges explicit visible hostiles with follower-backed visible actors.
- Emit follower monster records as `location_hostiles`.
- Add backend tests for inclusion, exclusion, dedupe, and legacy minimal records.

This phase fixes the UI path whenever follower state exists.

### Phase 2: Add Structured Runtime Writer

- Add `updateSceneFollower` action handling or an equivalent validated runtime hook.
- Update prompts so the LLM emits this action when it establishes captives, escorts, guarded guides, or parley actors.
- Validate entity identity, location, disposition, and combat/death consistency.
- Persist updates through `utils/scene_follower_state.py`.

This phase lets narrative outcomes automatically become Python-authoritative follower state.

### Phase 2B: Recruitment Identity Hardening

- Preserve module-authored display identity when `updatePartyNPCs` recruits a module NPC.
- Stop broad fuzzy character-file matching from renaming recruited module NPCs.
- If an existing character file is reused, store it as `character_file_ref` or equivalent metadata.
- Add source metadata to `partyNPCs` entries where possible: `source_module`, `source_npc_name`, `source_entity_slug`, `recruited_from_location_id`.
- Suppress or consume matching current-location NPC entries when the same source identity is now in the party.

This phase prevents Sylara-style duplicate actors and prevents prior-session character files from becoming accidental authority over current module NPC identity.

### Phase 3: Lifecycle Cleanup

- Add removal/update triggers for release, escape, death, party join, and combat start.
- Decide whether hidden-but-tracked followers should remain in `scene_followers.json` for continuity.
- Add UI label support for disposition if desired.

## Tests

Recommended coverage:

- Generic `location.monsters` remain excluded from strip hostiles.
- Explicit `visibleHostiles` still render.
- Follower monster at current location renders as `location_hostile` with monster media metadata.
- Follower at another location does not render.
- Follower already represented as PC, party NPC, location NPC, or explicit hostile is deduped.
- Minimal legacy follower records do not crash or force visibility.
- Invalid `updateSceneFollower` entity is rejected.
- Dead/combat-contradictory updates are rejected.
- Release/escape/death transitions remove or hide the strip entry.
- Recruiting `Thorn-Touched Dryad Sylara` preserves that canonical name even when `characters/dryad_sylara.json` exists.
- Recruitment may link `dryad_sylara.json` as a reference, but must not rename the recruited module NPC to `Dryad Sylara` unless the module canon says so.
- A party NPC with `source_npc_name: Thorn-Touched Dryad Sylara` suppresses the matching current-location NPC in the strip.
- Existing exact-name party NPC recruitment still works for non-module or already-canonical character files.

## Open Questions

- Should `updateSceneFollower` be a public LLM action, or should follower updates be inferred only from already-validated actions such as encounter outcomes and plot updates?
- Should non-hostile follower NPCs render through `location_npcs`, or should there be a new neutral `scene_actors` lane?
- Should `visible_in_strip` default to true for `following/held/parleying`, or should it always be explicit?
- How much of follower lifecycle should persist into memory/diary systems versus only runtime UI state?
- Should combat start automatically convert visible hostile followers into encounter candidates, or should that remain a separate `createEncounter` decision?
- Should `partyNPCs` remain a lightweight name/role list with optional metadata, or should recruited NPCs move to a richer party actor schema?
- Should a recruited module NPC update the source location JSON immediately, or should runtime party/follower state override source-location presence at render time?

## Initial Recommendation

Implement Phase 1 and Phase 2 together if possible.

Phase 1 alone creates the display path but still requires follower records to exist. Phase 2 is what makes the system useful in live play: the LLM can establish narrative state through a structured action, Python validates it, and the UI updates from Python reality.

Keep the action narrow, validated, and reversible. That gives the LLM DM broad narrative authority without letting prose alone mutate reality.
