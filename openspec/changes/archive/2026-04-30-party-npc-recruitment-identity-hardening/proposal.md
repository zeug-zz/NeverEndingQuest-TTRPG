# Change: Party NPC Recruitment Identity Hardening

## Problem
Recruiting a module-authored NPC can currently collapse that NPC into an older persistent character-file identity when fuzzy character matching finds a partial match. In current gameplay, the party recruited the module NPC `Thorn-Touched Dryad Sylara`, but `party_tracker.json` ended up with `Dryad Sylara` because an older `characters/dryad_sylara.json` file matched fuzzily. The current location still listed `Thorn-Touched Dryad Sylara`, so the top strip showed both the allied `Dryad Sylara` and the authored location NPC `Thorn-Touched Dryad Sylara`.

This is partly exposed by prior-session data, but the underlying bug is fundamental: fuzzy character-file matching is allowed to override the module-authored identity being recruited.

## Objective
Preserve module-authored NPC identity through recruitment and prevent duplicate strip actors when a current-location NPC becomes a party NPC.

The implementation MUST:
- Preserve the canonical module NPC display name when `updatePartyNPCs` recruits a module-authored NPC.
- Prevent fuzzy character-file matches from renaming a recruited module NPC.
- Allow existing character files to be linked for continuity/stats/media without becoming identity authority unless they exactly match or carry matching source metadata.
- Add optional source identity metadata to party NPC entries where available.
- Suppress current-location NPC duplicates when a party NPC has the same source identity.
- Preserve compatibility with existing lightweight `partyNPCs` entries that only contain `name` and `role`.

## Non-Goals
- Do not remove or rename existing character files.
- Do not require immediate migration of all existing `partyNPCs` entries.
- Do not prohibit exact-name character-file reuse for NPCs that are already canonical.
- Do not convert all party NPCs to full character sheets in this change.
- Do not weaken module NPC authority or hidden NPC validation.

## Rollout And Fallback
The change is additive. New metadata fields can be ignored by older code paths. Existing `partyNPCs` entries remain valid. If source identity cannot be resolved, recruitment should fall back to existing name/role behavior without using broad fuzzy matching to rename the actor.

Rollback is safe by ignoring source metadata and returning to display-name-only strip dedupe, though the duplicate/rename bug would return.

## Merge Safety And Compatibility
This is TABLETOP MODE hardening. Changes SHOULD be limited to `core/ai/action_handler.py`, identity helper utilities, `web/extensions/tabletop_socket_handlers.py`, and targeted tests. Single-player behavior should not change unless it also uses the same party NPC route.

## Impacted Areas
- `core/ai/action_handler.py`
- `utils/npc_arrival_validator.py` or a shared NPC identity helper if source identity extraction is centralized
- `updates/update_character_info.py` fuzzy match use only if a safer recruitment-specific wrapper is needed
- `web/extensions/tabletop_socket_handlers.py`
- `web/extensions/missing_media_autogen.py` only if allied portrait policy needs source metadata awareness
- targeted regression tests under `scripts/`
