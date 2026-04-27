# Design: Scene Anchor Party Identity Collision

## Boundary

Scene anchors are authored or runtime scene authority. Party members are mobile mechanical entities. When an anchor alias equals a party member's base name, the party member identity should win for bare-name mentions at the party's current location.

## Algorithm

1. Extend `evaluate_location_exclusivity_decision()` with optional `party_member_names`.
2. Canonicalize party names using the same style as the guard's text normalization: lowercase, punctuation-insensitive, underscore/space equivalent.
3. When evaluating an off-location anchor alias:
   - If the alias exactly matches a current party member canonical name, skip that alias only.
   - Do not skip aliases that contain extra identity/state words.
   - Continue evaluating all other aliases for the same anchor.
4. Pass `party_tracker_data.get("partyMembers", [])` from `main.py` guard callsite.

## Examples

Allowed:
- Party contains `Vitreol`.
- Off-location anchor has alias `Vitreol` and `corrupted Vitreol`.
- Current-location narration says `Vitreol wakes by the cold fire.`
- The bare `Vitreol` alias is ignored as a party identity collision.

Blocked:
- Same state, narration says `corrupted Vitreol stands before you.`
- `corrupted Vitreol` is not an exact party-name alias and remains off-location anchor presence.

## Compatibility

Existing calls without `party_member_names` MUST preserve current behavior.

## Rollback

The optional argument can be removed and the guard reverts to current strict metadata behavior.
