# Tasks: Scene Follower Thumbnail State

## 1. Follower Metadata Contract
- [x] 1.1 Extend `utils/scene_follower_state.py` schema validation to allow optional metadata fields while preserving existing required fields.
- [x] 1.2 Add helper functions for normalized entity id, display name, entity type, disposition, visibility, and source identity fields.
- [x] 1.3 Add tests proving legacy minimal records still validate and load.

## 2. Validated Runtime Writer
- [x] 2.1 Add `updateSceneFollower` action constant and dispatch path in `core/ai/action_handler.py`.
- [x] 2.2 Validate entity grounding against module monsters, bestiary, module NPC authority, existing follower records, or same-turn validated state.
- [x] 2.3 Validate current location against party tracker/module topology when location is provided.
- [x] 2.4 Validate lifecycle state and disposition enums.
- [x] 2.5 Implement create/update/move/hide/remove behavior for supported states.
- [x] 2.6 Add structured error responses for invalid updates.

## 3. Prompt And Validation Guidance
- [x] 3.1 Add compact `updateSceneFollower` guidance to `prompts/system_prompt_compressed.txt`.
- [x] 3.2 Mirror essential guidance in `prompts/system_prompt.txt` if required by uncompressed mode.
- [x] 3.3 Update validation prompt guidance if validator currently rejects the new action shape.

## 4. Party Strip Integration
- [x] 4.1 Add a helper in `web/extensions/tabletop_socket_handlers.py` that extracts current-location visible follower actors.
- [x] 4.2 Merge monster-like visible followers into `location_hostiles` outside active combat.
- [x] 4.3 Dedupe follower actors against party members, party NPCs, current-location NPCs, and explicit visible hostiles.
- [x] 4.4 Preserve the existing rule that generic `location.monsters` are not rendered as visible hostiles.

## 5. Lifecycle Cleanup
- [x] 5.1 Hide/remove follower strip visibility when state becomes `hidden`, `released`, `escaped`, `dead`, `joined_party`, or `combat_started`.
- [x] 5.2 Ensure combat startup does not treat a follower record alone as combat-valid.

## 6. Regression Coverage
- [x] 6.1 Test explicit `visibleHostiles` still render.
- [x] 6.2 Test generic `location.monsters` remain hidden from the strip.
- [x] 6.3 Test a current-location visible monster follower renders as `location_hostile` with monster media metadata.
- [x] 6.4 Test off-location followers do not render.
- [x] 6.5 Test follower dedupe against party/location actors.
- [x] 6.6 Test invalid follower updates fail closed without mutating state.

## 7. Verification
- [x] 7.1 Run `.venv/bin/python -m py_compile utils/scene_follower_state.py core/ai/action_handler.py web/extensions/tabletop_socket_handlers.py`.
- [x] 7.2 Run targeted tests for scene follower state and party strip payloads.
- [x] 7.3 Run `openspec validate scene-follower-thumbnail-state`.
