# Change: Scene Follower Thumbnail State

## Problem
The non-combat tabletop thumbnail strip already renders party members, allied NPCs, current-location NPCs, and explicitly declared visible hostile presences. It does not have an authoritative runtime source for transient narrated actors that travel with the party without becoming party NPCs, such as captives, guarded guides, parleying enemies, or hostile monsters under escort.

In current gameplay, Corrupted Ranger Thane was captured alive and became a guarded guide, then the party moved to another location. Thane has valid monster data and media, but he is no longer an authored current-location NPC/monster and is not a party NPC. Because no durable follower/visible-scene state represents him, the top strip cannot show his artwork.

The existing archived `tt-following-scene-entity-state` foundation persists minimal follower records and lets narrator exclusivity validation respect them. This change extends that foundation so visible follower actors can be safely surfaced in the UI and managed through validated lifecycle transitions.

## Objective
Add a bounded, Python-authoritative scene follower thumbnail contract so transient non-party actors can remain visible in the non-combat strip when they are currently present with the party.

The implementation MUST:
- Preserve the existing minimal `scene_followers.json` record compatibility.
- Add optional follower metadata for display, media routing, disposition, visibility, and source identity.
- Provide a validated runtime update path for follower creation, movement, visibility, disposition, and cleanup.
- Surface current-location visible monster/hostile followers through the existing `location_hostiles` payload lane outside combat.
- Continue to avoid rendering generic `location.monsters` seeds, which may represent hidden or potential threats.
- Preserve scene follower non-combat semantics; follower records MUST NOT make an entity combat-valid by themselves.

## Non-Goals
- Do not scrape conversation history or compressed summaries at render time to infer current actors.
- Do not render every authored monster seed in a location.
- Do not automatically convert scene followers into party NPCs, PCs, or combatants.
- Do not replace the existing `visibleHostiles`/`sceneHostiles` explicit location metadata path.
- Do not require existing follower records to be migrated before the game can start.

## Rollout And Fallback
The change is additive. If follower metadata is absent, existing follower records continue working for location exclusivity. If follower loading or validation fails, the party strip should omit follower-backed thumbnails and continue rendering party members, allied NPCs, location NPCs, and explicit visible hostiles.

Rollback is safe by ignoring the new metadata fields and disabling the new socket payload merge path. No canonical module data needs to change.

## Merge Safety And Compatibility
This is TABLETOP MODE extension work. Host-file changes SHOULD be limited to small hooks in `core/ai/action_handler.py`, `web/extensions/tabletop_socket_handlers.py`, prompts, and tests. The existing single-player path should be unaffected because follower thumbnail emission depends on runtime party/tabletop socket payloads.

## Impacted Areas
- `utils/scene_follower_state.py`
- `core/ai/action_handler.py`
- `web/extensions/tabletop_socket_handlers.py`
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- validation prompt mirrors if action validation requires explicit guidance
- targeted regression tests under `scripts/`
