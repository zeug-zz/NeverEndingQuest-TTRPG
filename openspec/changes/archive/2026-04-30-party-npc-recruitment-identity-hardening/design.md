# Design: Party NPC Recruitment Identity Hardening

## Architecture Boundary
Module-authored NPC identity is authoritative for recruitment when the requested NPC resolves to a module NPC. Character files may provide mechanical/profile continuity, but they must not replace the module-authored display identity unless the file is an exact canonical match or has matching source metadata.

## Party NPC Metadata
Existing party NPC entries remain valid:

```json
{
  "name": "Scout Kira",
  "role": "Companion"
}
```

When the recruited actor is a module NPC, new entries SHOULD include optional source metadata:

```json
{
  "name": "Thorn-Touched Dryad Sylara",
  "role": "Companion",
  "source_module": "The_Thornwood_Watch",
  "source_npc_name": "Thorn-Touched Dryad Sylara",
  "source_entity_slug": "thorn_touched_dryad_sylara",
  "character_file_ref": "dryad_sylara",
  "recruited_from_location_id": "NC02"
}
```

`character_file_ref` is a link, not identity authority. It may point to an existing character file that is useful for profile/stats/media continuity, but it must not force `name` to change from the module canonical NPC name.

## Recruitment Resolution Order
`updatePartyNPCs` recruitment should resolve identity in this order:
1. Resolve the requested name against module NPC authority for the current module.
2. If module identity is resolved, preserve that canonical display name and source metadata.
3. Look for an exact normalized character-file match or a file with matching source metadata to link as `character_file_ref`.
4. If only broad fuzzy character-file matches exist, do not rename the recruited actor. Optionally link the best candidate only if it passes a stricter reviewable predicate.
5. If no module identity exists, preserve existing behavior for non-module or exact character-file recruits, with existing safeguards.

## Fuzzy Matching Guard
The existing `find_character_file_fuzzy()` behavior is useful in some contexts, but recruitment needs stricter identity authority. A module NPC name such as `Thorn-Touched Dryad Sylara` must not be replaced by a shorter stale file display name such as `Dryad Sylara` simply because token-subset matching succeeds.

## Location NPC Dedupe
The party strip currently dedupes current-location NPCs against party NPCs by display-name normalization. This is insufficient when the party NPC has been recruited under a related alias or linked source identity.

The socket handler should build dedupe keys from:
- normalized display name;
- `source_npc_name`;
- `source_entity_slug`;
- module/location NPC canonical identity when available.

If a current-location NPC matches a party NPC source identity, the location NPC should be suppressed from `location_npcs` because that scene actor has transitioned into the party.

## Relationship To Scene Follower Lifecycle
Recruitment is a scene actor lifecycle transition: `location_present -> party_npc/allied`. This change hardens the party NPC branch. The sibling `scene-follower-thumbnail-state` change hardens the non-party follower branch, such as `location_present -> follower/captive/guarded_guide`.

## Observability
Recruitment should log whether the source identity came from module NPC authority, exact character-file identity, or fallback name/role input. When fuzzy candidates are rejected as identity authority, logs SHOULD include the requested name and rejected file slug.

## Backward Compatibility
Existing `partyNPCs` entries without metadata must continue to render and function. Dedupe should fall back to display-name normalization when metadata is absent.

## Rollback
Rollback can ignore the metadata and use existing party NPC name/role entries. No canonical module data changes are required.
