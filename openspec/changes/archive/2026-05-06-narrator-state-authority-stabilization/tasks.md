## 1. Action Authority Normalization

- [x] 1.1 Add a shared final-action normalization helper for narrator action lists.
- [x] 1.2 Convert unsafe same-module `updatePartyTracker.currentLocationId` changes to `transitionLocation` when target differs from current location.
- [x] 1.3 Strip no-op `currentLocationId` tracker keys while preserving non-location tracker fields.
- [x] 1.4 Preserve valid cross-module `updatePartyTracker` updates.
- [x] 1.5 Run the normalizer immediately before final action processing in `main.py` and any equivalent final action processing path.
- [x] 1.6 Emit structured debug events for normalized, stripped, and rejected action intents.

**Verification for 1.1-1.6**: `.venv/bin/python -m py_compile main.py utils/action_normalization.py` or equivalent helper path passes.

## 2. Party Tracker Merge Guard

- [x] 2.1 Harden `_merge_party_tracker_updates()` or the `ACTION_UPDATE_PARTY_TRACKER` branch to reject unsafe same-module location writes.
- [x] 2.2 Ensure rejected unsafe tracker writes do not persist `party_tracker.json`.
- [x] 2.3 Preserve non-location tracker fields such as `resolvedHostilesByLocation`.
- [x] 2.4 Preserve valid cross-module tracker updates.
- [x] 2.5 Surface a user-safe error for unsafe location writes that bypass normalization.

**Verification for 2.1-2.5**: `.venv/bin/python -m py_compile core/ai/action_handler.py utils/party_tracker_merge.py` passes.

## 3. Scene Follower Transition Sync

- [x] 3.1 Add a scene follower helper that moves only conservative traveling followers from old location to new location.
- [x] 3.2 Call the helper after successful `transitionLocation` commits.
- [x] 3.3 Keep transition success fail-open if follower sync fails.
- [x] 3.4 Log moved, skipped, and failed follower sync outcomes.
- [x] 3.5 Ensure absent or location-bound followers do not move automatically.

**Verification for 3.1-3.5**: `.venv/bin/python -m py_compile core/ai/action_handler.py utils/scene_follower_state.py` passes.

## 4. DM Note And Prompt Contract Alignment

- [x] 4.1 Add a compact `SCENE FOLLOWERS PRESENT HERE` section to DM Note generation.
- [x] 4.2 Include present followers only when their `current_location` matches the effective current location.
- [x] 4.3 Update `@FOLLOWER_STATE` prompt wording to reference deterministic follower records and `updateSceneFollower`.
- [x] 4.4 Update narrator and validation prompts so same-module movement uses `transitionLocation`, not `updatePartyTracker`.
- [x] 4.5 Ensure prompt wording keeps cross-module `updatePartyTracker` valid.

**Verification for 4.1-4.5**: `.venv/bin/python -m py_compile utils/multi_pc_dm_note.py` passes.

## 5. Regression Tests

- [x] 5.1 Add tests for no-module `updatePartyTracker.currentLocationId` conversion to `transitionLocation`.
- [x] 5.2 Add tests for same-location no-op tracker stripping while preserving world-state fields.
- [x] 5.3 Add tests proving unsafe same-module tracker writes are rejected at the merge/action-handler layer.
- [x] 5.4 Add tests proving cross-module tracker updates remain valid.
- [x] 5.5 Add tests for traveling follower sync on transition.
- [x] 5.6 Add tests proving location-bound or absent followers do not move.
- [x] 5.7 Add tests proving DM Note includes present scene followers independently of `partyNPCs`.
- [x] 5.8 Add prompt source-contract tests for `transitionLocation`, `updatePartyTracker`, and `@FOLLOWER_STATE` wording.

**Verification for 5.1-5.8**: `.venv/bin/python scripts/test_update_party_tracker_merge.py` and `.venv/bin/python scripts/test_scene_follower_transition_sync.py` or equivalent focused suites pass.

## 6. Full Validation

- [x] 6.1 Run `.venv/bin/python scripts/test_travel_state_sync_guard.py`.
- [x] 6.2 Run `.venv/bin/python scripts/test_npc_arrival_state_sync.py`.
- [x] 6.3 Run `openspec validate narrator-state-authority-stabilization`.
- [x] 6.4 Run targeted ASCII compliance for modified Python files or `python3 scripts/check_ascii_compliance.py --summary-only` before commit.
