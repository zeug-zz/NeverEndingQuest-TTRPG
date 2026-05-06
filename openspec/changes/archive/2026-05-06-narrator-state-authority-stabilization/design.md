## Context

Narrator action authority is currently distributed across several layers. Raw LLM actions are preprocessed in `main.py`, validation may insert inferred actions, and `core/ai/action_handler.py` applies actions through domain-specific handlers. The party tracker merge helper accepts broad location fields and writes them directly into `worldConditions`.

This change introduces a deterministic boundary: every final action list must pass through a shared authority normalizer before action processing, and the party tracker merge helper must refuse unsafe same-module location writes if any caller bypasses that boundary.

Scene follower state is also currently outside the narrator's strongest truth surface. Followers can be visible in GUI/runtime state while absent from DM Note context. A follower that semantically travels with the party can remain at the prior location after `transitionLocation`, causing later location exclusivity and narrator decisions to diverge.

## Contract Layer (MUST)

### Action Normalization Boundary

- The runtime MUST normalize final narrator action lists before calling action handlers.
- The normalizer MUST convert same-module `updatePartyTracker.currentLocationId` changes into `transitionLocation` when the target differs from the current party location and the target can be treated as a same-module location intent.
- The normalizer MUST strip no-op location keys when `updatePartyTracker.currentLocationId` equals the current location.
- The normalizer MUST preserve non-location tracker fields such as `resolvedHostilesByLocation`.
- The normalizer MUST preserve valid cross-module tracker updates.
- The normalizer MUST return structured normalization events for logging and tests.

### Party Tracker Merge Guard

- `_merge_party_tracker_updates()` or the `ACTION_UPDATE_PARTY_TRACKER` branch MUST reject unsafe same-module location changes if normalization was bypassed.
- The guard MUST NOT write `party_tracker.json` when rejecting an unsafe same-module location change.
- The guard MUST keep cross-module tracker updates and non-location world-state updates valid.

### Scene Follower Sync

- Successful same-module and cross-module transitions MUST attempt to sync only followers that are present, currently at the old party location, and conservatively classified as traveling with the party.
- Follower sync MUST fail open; transition success MUST NOT be rolled back by follower persistence failure.
- Follower sync MUST not move location-bound or absent follower records.

### DM Note Projection

- DM Note generation MUST include present scene followers at the current effective location in a compact, bounded section.
- The section MUST be present independently of `partyNPCs`, so follower-only scenes are visible to the narrator.
- Entries MUST be ASCII-only and bounded to avoid prompt bloat.

## Guidance Layer (SHOULD)

### Normalizer Shape

Prefer a shared helper such as:

```python
def normalize_action_list_for_authority(actions, party_tracker_data):
    """Return normalized actions and structured normalization events."""
```

The helper should live in `utils/action_normalization.py` unless an existing narrator authority utility is a better fit.

### Merge Guard Shape

Prefer adding explicit context to `_merge_party_tracker_updates(...)` instead of embedding module lookup inside the merge helper:

```python
def _merge_party_tracker_updates(current_party_data, parameters, *, current_module=None, allow_same_module_location_write=False):
    ...
```

Callers should pass the current module when available. Unsafe location write failures should be represented as structured results rather than warning-only logs.

### Follower Eligibility

Initial traveling-follower eligibility should be conservative:

- `lifecycle_state == "present"`
- `current_location == old_location_id`
- `visible_in_strip == True` or disposition indicates travel
- disposition in `guarded_guide`, `following`, `captive`, `held`, `parleying`, `companion`, `escorted`

If a later schema adds explicit `travels_with_party`, that field should supersede heuristic disposition checks.

### DM Note Section

Recommended section:

```text
--- SCENE FOLLOWERS PRESENT HERE ---
Corrupted Ranger Thane (monster, guarded_guide, currentLocation=NC05): present with party; not a PC.
```

## Rollback

- If action normalization is too broad, keep the fail-closed merge guard and temporarily narrow normalization to no-op stripping plus diagnostics.
- If follower sync is too broad, restrict eligibility to explicit `visible_in_strip == True` and guide/captive dispositions only.
- Prompt wording can be reverted independently if runtime guards remain in place.
