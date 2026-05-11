# Scene Follower Captive Lifecycle Sync

Status: Draft for review
Date: 2026-05-11
Scope: Small runtime patch with regression coverage

## Problem

Scene follower continuity failed for `Corrupted Ranger Thane` during Thornwood Watch travel.

Observed live state:

```json
{
  "entity_id": "corrupted_ranger_thane",
  "current_location": "NC04",
  "display_name": "Corrupted Ranger Thane",
  "entity_type": "monster",
  "monster_type": "Corrupted Ranger Thane",
  "visible_in_strip": true,
  "lifecycle_state": "restrained",
  "disposition": "guarded_guide",
  "source_module": "The_Thornwood_Watch",
  "source_npc_name": "Corrupted Ranger Thane",
  "source_entity_slug": "corrupted_ranger_thane",
  "recruited_from_location_id": "NC04"
}
```

The follower record existed, but the runtime treated it as absent because two code paths only accept `lifecycle_state == "present"`:

- `utils/scene_follower_state.py::_is_traveling_follower_record(...)`
- `utils/multi_pc_dm_note.py::format_present_scene_followers(...)`

This caused Thane to remain stuck at `NC04` after party travel, disappear from DM Note at `NC02`, and get rejected by narrator/validator context as nonexistent.

## Root Cause

The scene follower system uses two overlapping concepts as if they were one:

- Presence lifecycle: whether the entity is physically with the party or absent from the current scene.
- Relationship/control posture: whether the entity is restrained, captive, guarded, friendly, etc.

`restrained` is a valid captive posture, but current projection and travel sync interpret it as not present.

## Desired Behavior

Captives, restrained guides, held prisoners, escorted entities, and guarded guides should continue to travel and appear in DM Note when their record says they are visible/present with the party.

Hidden, escaped, released, dead, joined-party, and combat-started records must remain excluded.

## Minimal Patch Contract

### File: `utils/scene_follower_state.py`

Add one central helper and use it everywhere instead of strict `lifecycle_state == "present"` checks.

Proposed constants:

```python
_FOLLOWER_PRESENT_LIFECYCLE_STATES = {
    "present",
    "following",
    "held",
    "captive",
    "restrained",
    "parleying",
    "guarded_guide",
    "escorted",
}
```

Proposed helper:

```python
def follower_is_scene_present(record: Dict[str, Any]) -> bool:
    """Return True when a follower should count as physically present in scene truth."""
    if not isinstance(record, dict):
        return False

    lifecycle_state = normalize_scene_follower_disposition(
        record.get("lifecycle_state") or record.get("state")
    )
    disposition = normalize_scene_follower_disposition(record.get("disposition"))

    if lifecycle_state in _FOLLOWER_HIDDEN_STATES:
        return False
    if disposition in _FOLLOWER_HIDDEN_STATES:
        return False

    if lifecycle_state in _FOLLOWER_PRESENT_LIFECYCLE_STATES:
        return True
    if disposition in _FOLLOWER_TRAVEL_DISPOSITIONS:
        return True
    if follower_visible_in_strip(record) and disposition in {"friendly", "neutral", "hostile", "guarded_guide"}:
        return True
    return False
```

Update `_FOLLOWER_DISPOSITION_VALUES` to include `captive`, `restrained`, `companion`, and `escorted` if not already accepted by `updateSceneFollower` validation. This should match `_FOLLOWER_TRAVEL_DISPOSITIONS` so the action path can persist these states without rejection.

Update `_is_traveling_follower_record(...)`:

```python
if not follower_is_scene_present(record):
    return False
```

Keep the existing same-location check and travel disposition logic, but allow visible restrained/captive records to pass when their disposition is travel-capable.

### File: `utils/multi_pc_dm_note.py`

Import and use `follower_is_scene_present(...)`.

Replace:

```python
if lifecycle_state != "present":
    continue
```

With:

```python
if not follower_is_scene_present(normalized):
    continue
```

Keep the current location check. DM Note should only show followers whose record location matches current party location.

Suggested line text stays compact:

```text
Corrupted Ranger Thane (monster, guarded_guide, restrained, currentLocation=NC02): scene follower with party; not a PC.
```

### File: `utils/authoritative_state_packet.py`

Add current-location scene followers to the packet so validator/narrator context does not claim valid followers are nonexistent.

Recommended packet addition under `party` or new top-level `scene_followers`:

```json
"scene_followers": [
  {
    "entity_id": "corrupted_ranger_thane",
    "display_name": "Corrupted Ranger Thane",
    "entity_type": "monster",
    "monster_type": "Corrupted Ranger Thane",
    "lifecycle_state": "restrained",
    "disposition": "guarded_guide",
    "current_location": "NC02",
    "source_module": "The_Thornwood_Watch",
    "source_npc_name": "Corrupted Ranger Thane",
    "source_entity_slug": "corrupted_ranger_thane"
  }
]
```

Rules:

- Include only records whose `current_location` equals current party location.
- Exclude cleanup/hidden states.
- Keep output bounded, e.g. first 8 records.
- Fail open on follower store read errors.

### File: `main.py`

When building `follower_records` for location exclusivity guard, filter out cleanup states but do not require `present` exactly.

Use `normalize_scene_follower_record(...)` and `follower_is_scene_present(...)` so `restrained` and `captive` followers still authorize present-scene mentions at their tracked location.

### Optional Context Improvement

If validator still rejects monster-backed followers, add a compact validation context line from authoritative packet:

```text
@SCENE_FOLLOWERS_PRESENT: Corrupted Ranger Thane [monster, guarded_guide, restrained] @NC02
```

This is lower priority if `AUTHORITATIVE_STATE_PACKET` already includes the follower and validator reads it.

## Tests

Extend `scripts/test_scene_follower_transition_sync.py`.

### Add: restrained captive moves on transition

Fixture:

```json
{
  "entity_id": "corrupted_ranger_thane",
  "display_name": "Corrupted Ranger Thane",
  "entity_type": "monster",
  "monster_type": "Corrupted Ranger Thane",
  "disposition": "guarded_guide",
  "lifecycle_state": "restrained",
  "current_location": "NC04",
  "since_turn": 1,
  "visible_in_strip": true
}
```

Action:

```python
result = follower_state.sync_traveling_followers_to_location("NC04", "NC02")
```

Assert:

- `corrupted_ranger_thane` in `result["moved"]`
- stored `current_location == "NC02"`

### Add: restrained captive appears in DM Note

Same fixture at `NC02`.

Assert:

- DM Note contains `--- SCENE FOLLOWERS PRESENT HERE ---`
- DM Note contains `Corrupted Ranger Thane`
- DM Note contains `restrained` or equivalent lifecycle marker

### Add: cleanup states still excluded

Test `released`, `escaped`, `dead`, `joined_party`, `combat_started`, and `hidden` do not move and do not appear in DM Note.

### Add: authoritative packet includes current follower

New or existing test file for `utils/authoritative_state_packet.py`.

Assert current-location restrained follower appears in `scene_followers` and other-location follower does not.

## Verification Commands

```bash
.venv/bin/python -m py_compile utils/scene_follower_state.py utils/multi_pc_dm_note.py utils/authoritative_state_packet.py main.py scripts/test_scene_follower_transition_sync.py
.venv/bin/python scripts/test_scene_follower_transition_sync.py
.venv/bin/python scripts/test_narrator_prompt_validation_refactor.py
.venv/bin/python scripts/test_travel_state_sync_guard.py
```

If authoritative packet tests are added in a separate file, include that test command too.

## Manual Runtime Recovery After Patch

Current live store has Thane at `NC04` while party is at `NC02`. After patch, this will not auto-replay past transitions. Either:

1. Manually restore current state once:

```json
{
  "followers": [
    {
      "entity_id": "corrupted_ranger_thane",
      "current_location": "NC02",
      "since_turn": 1,
      "display_name": "Corrupted Ranger Thane",
      "entity_type": "monster",
      "monster_type": "Corrupted Ranger Thane",
      "visible_in_strip": true,
      "lifecycle_state": "restrained",
      "disposition": "guarded_guide",
      "source_module": "The_Thornwood_Watch",
      "source_npc_name": "Corrupted Ranger Thane",
      "source_entity_slug": "corrupted_ranger_thane",
      "recruited_from_location_id": "NC04"
    }
  ]
}
```

2. Or ask the narrator for an explicit `updateSceneFollower` correction after patch.

## Builder Prompt

Implement the scene follower captive lifecycle sync patch described in `plans/scene-follower-captive-lifecycle-sync.md`.

Constraints:

- Keep the patch minimal and deterministic.
- Do not add schemas or new runtime storage formats.
- Preserve existing cleanup semantics for hidden, released, escaped, dead, joined_party, and combat_started.
- Treat restrained/captive/held/guarded-guide followers as scene-present and travel-eligible only when the record is at the old party location and not cleanup-hidden.
- Keep all new Python source ASCII-only.
- Use existing safe JSON helpers and enhanced logger patterns.
- Add regression tests before or with implementation.

Expected files:

- `utils/scene_follower_state.py`
- `utils/multi_pc_dm_note.py`
- `utils/authoritative_state_packet.py`
- `main.py`
- `scripts/test_scene_follower_transition_sync.py`
- Optional: authoritative packet test file if clearer.

Acceptance criteria:

- A `restrained` + `guarded_guide` + visible follower at the old party location moves during `transitionLocation` sync.
- The same follower appears in DM Note when at the current party location.
- Cleanup/absent follower states remain excluded.
- Current-location scene followers are exposed in authoritative packet context.
- Targeted verification commands pass.
