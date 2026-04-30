# Tasks: Party NPC Recruitment Identity Hardening

## 1. Recruitment Identity Resolution
- [x] 1.1 Add or reuse a helper that resolves a requested party NPC name against current module NPC authority.
- [x] 1.2 Update `core/ai/action_handler.py` `updatePartyNPCs` add path to preserve module canonical display names when resolved.
- [x] 1.3 Prevent broad fuzzy character-file matches from overwriting module canonical names.
- [x] 1.4 Link exact or source-matching character files as metadata without renaming the recruited actor.
- [x] 1.5 Preserve existing behavior for exact-name/non-module recruits.

## 2. Party NPC Source Metadata
- [x] 2.1 Add optional source metadata fields to newly recruited module NPC party entries.
- [x] 2.2 Include `source_module`, `source_npc_name`, `source_entity_slug`, and `recruited_from_location_id` when known.
- [x] 2.3 Include `character_file_ref` only when an existing character file is safely linked.
- [x] 2.4 Ensure existing `partyNPCs` entries with only `name` and `role` remain valid.

## 3. Strip Dedupe By Source Identity
- [x] 3.1 Update `web/extensions/tabletop_socket_handlers.py` current-location NPC dedupe to use source metadata when present.
- [x] 3.2 Suppress current-location NPCs that match recruited party NPC source identity.
- [x] 3.3 Preserve existing display-name dedupe fallback for legacy entries.

## 4. Allied Portrait Policy Review
- [x] 4.1 Verify `web/extensions/missing_media_autogen.py` uses party NPC identity consistently after recruitment metadata is added.
- [x] 4.2 If needed, make portrait generation prefer source identity/media slug for module-authored recruits while preserving existing `dryad_sylara` assets when exact identity is intended.

## 5. Regression Coverage
- [x] 5.1 Test recruiting `Thorn-Touched Dryad Sylara` preserves that canonical name when `characters/dryad_sylara.json` exists.
- [x] 5.2 Test the old character file can be linked as `character_file_ref` without changing party NPC `name`.
- [x] 5.3 Test current-location `Thorn-Touched Dryad Sylara` is suppressed from `location_npcs` when the party NPC source identity matches.
- [x] 5.4 Test exact-name character-file recruits still work.
- [x] 5.5 Test legacy `partyNPCs` entries without source metadata still render and dedupe by display name.

## 6. Verification
- [x] 6.1 Run `.venv/bin/python -m py_compile core/ai/action_handler.py web/extensions/tabletop_socket_handlers.py`.
- [x] 6.2 Run targeted recruitment identity and party strip tests.
- [x] 6.3 Run `openspec validate party-npc-recruitment-identity-hardening`.
