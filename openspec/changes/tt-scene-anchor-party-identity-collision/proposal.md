# tt-scene-anchor-party-identity-collision

## Why

Location-exclusive scene anchors are valuable guardrails, but the Vitreol case showed that an off-location anchor alias can collide with a current party member's base name. `vitreol_thrall` at NC02 used alias `Vitreol`, causing present-scene narration about the active PC Vitreol at NC04 to fail as an off-location anchor violation.

The guard should continue to block distinctive off-location anchor instantiation while allowing exact bare party-member names to refer to party members at the current location.

## What Changes

- The narrator location exclusivity guard MUST accept optional current party member identities.
- Exact bare aliases that canonicalize to current party members MUST NOT trigger off-location scene-anchor failure by themselves.
- Distinctive aliases such as `corrupted Vitreol`, `Voidstone thrall`, or `vitreol_thrall` MUST remain protected and fail when instantiated off-location without transition/move state.
- The runtime MUST pass party member names from `party_tracker.json` into the guard.

## Non-Goals

- Do not weaken scene anchor exclusivity generally.
- Do not move scene anchors between locations.
- Do not implement following scene entity state in this change.
- Do not edit module data aliases as the primary fix.

## Capabilities

- Modified capability: `tt-location-exclusive-scene-authority`
- New capability: `tt-scene-anchor-party-identity-collision`

## Impact

Affected code:
- `utils/narrator_location_exclusivity_guard.py`
- `main.py`
- `scripts/test_narrator_location_exclusivity_guards.py`

Risks:
- Over-broad party-name exemptions could allow real off-location anchor leakage. This is mitigated by allowing only exact bare party-name alias matches, not longer or distinctive aliases.

Fallback:
- If ambiguity remains, keep current fail-closed behavior for all non-exact aliases and log diagnostic details.
