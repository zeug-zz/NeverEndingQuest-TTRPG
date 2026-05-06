## Why

Recent GPT 5.4 Mini gametesting exposed narrator-side state drift where the model used broad `updatePartyTracker` actions for same-module movement and where scene followers remained mechanically anchored to old locations after party travel.

The current runtime already has several recovery guards, but authority is split across raw LLM actions, inferred travel actions, validation repair, and low-level party-tracker merges. A partial pre-processing guard in `main.py` only catches `updatePartyTracker.currentLocationId` when a `module` field is also present. It does not protect later-inserted actions or no-module same-module writes. As a result, unsafe tracker writes can still bypass `transitionLocation` and corrupt persisted party location truth.

Scene follower truth has a related gap. Runtime follower records exist in `data/runtime/scene_followers.json`, but successful party transitions do not move followers that are clearly traveling with the party, and DM Note generation does not project present scene followers as authoritative scene participants. The narrator therefore loses visibility of entities that the GUI and runtime guards consider present.

## What Changes

- **Central action normalization**: Add a shared normalization pass for final action lists before processing so same-module location writes are converted to `transitionLocation` or stripped when no-op.
- **Fail-closed tracker merge guard**: Harden the party tracker merge path so unsafe same-module location changes cannot persist even if normalization is bypassed.
- **Prompt contract tightening**: Narrow `updatePartyTracker` prompt wording to cross-module activation and tracker flags; same-module movement must use `transitionLocation`.
- **Scene follower transition sync**: Move only conservative traveling follower records from old party location to new party location after successful transitions.
- **Scene follower DM Note projection**: Add a compact present-scene-follower section so narrator truth surfaces include follower records that are present at the current scene.
- **Follower action contract alignment**: Align `@FOLLOWER_STATE` with actual `scene_followers.json` persistence and `updateSceneFollower`, not `moveBackgroundNPC` as follower location persistence.

## Capabilities

### New Capabilities

- `tt-action-authority-normalization`: Final narrator action lists are normalized through a shared authority pass before action processing.
- `tt-scene-follower-transition-sync`: Traveling scene followers remain co-located with the party after successful transitions.
- `tt-scene-follower-dm-note-projection`: Present scene followers are projected into the DM Note truth surface.

### Modified Capabilities

- `tt-travel-intent-state-sync-guard`: Same-module movement authority is centralized around `transitionLocation`.
- `tt-following-scene-entity-state`: Follower persistence contract is updated to reflect actual scene follower state authority.

## Non-Goals

- Do not rewrite the full narrator validation loop.
- Do not make `updatePartyTracker` a same-module location setter.
- Do not move every present scene follower automatically; only conservative traveling followers should sync.
- Do not change combat behavior in this change.
- Do not introduce provider-specific LLM behavior here.

## Impact

- **Affected code**: `main.py`, `core/ai/action_handler.py`, `utils/party_tracker_merge.py`, `utils/scene_follower_state.py`, `utils/multi_pc_dm_note.py`, narrator/validation prompts, and focused tests.
- **Runtime data**: `party_tracker.json` and `data/runtime/scene_followers.json` writes become more strongly guarded and synchronized.
- **Backward compatible**: Cross-module tracker updates remain valid. Existing `transitionLocation` behavior remains the canonical same-module movement path.
- **SP/MP compatibility**: Single-player movement remains compatible; follower sync only has effect when follower records exist.
- **Merge safety**: Host-file hooks should be minimal and marked with `# TABLETOP MODE:` comments.
- **Rollout risk**: Medium. Incorrect normalization could affect travel. Mitigation is fail-closed merge guarding plus targeted travel and follower tests.

## Fallback Strategy

If action normalization causes unintended travel rejection, the low-level merge guard should still prevent silent corruption. The normalizer can be temporarily limited to logging and no-op stripping while keeping the merge guard active. Follower sync is fail-open: transition success must not be rolled back if follower persistence fails.
