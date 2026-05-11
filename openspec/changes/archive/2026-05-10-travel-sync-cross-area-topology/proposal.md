## Why

Live Thornwood play exposed a reconcile-first travel validation failure when the party tried to return from Blighted Thornbriar Grove (`NC02`) toward Bandit Stronghold (`TW05`). The authored module graph contains a valid cross-area route through Corrupted Entry Cave (`NC01`) to Bandit Stronghold (`TW05`), but `travel_state_sync_guard` only treats direct adjacent IDs and current-area `known_location_ids` as topology-safe.

This caused the guard to reject a valid return destination as `not topology-safe`, triggering retry-loop failure even though the path is available in module topology. A later narration-only workaround succeeded only because the model described the next adjacent waypoint (`Doomed Explorer's Camp`) instead of committing the cross-area destination.

## What Changes

- Extend reconcile-first travel topology checks to recognize authored cross-area routes inside the current module.
- Reuse the same module graph authority already used by transition validation where practical, instead of widening safety by prompt memory or conversation history.
- Preserve strict blocking for unknown destinations, cross-module destinations, same-location no-ops, and unauthored teleport-style jumps.
- Add regression coverage for the Thornwood `NC02 -> TW05` route and rejection of non-reachable module locations.

## Capabilities

### New Capabilities

- `tt-travel-cross-area-topology`: Reconcile-first travel validation can validate same-module cross-area destinations through authored graph paths, not only current-area membership.

## Non-Goals

- Do not loosen cross-module travel rules.
- Do not infer arbitrary destinations from conversation history alone.
- Do not bypass `transitionLocation` validation or existing same-module movement authority.
- Do not change scene follower persistence rules except as needed for travel-sync regression coverage.
- Do not modify module JSON topology data in this slice unless tests prove existing authored edges are malformed.
- Do not archive until implementation and validation are complete.

## Impact

- **Affected code, later implementation:** `utils/travel_state_sync_guard.py`, `utils/authoritative_state_packet.py`, `main.py`, and focused tests around scene/travel sync.
- **Runtime behavior, later implementation:** A player can ask to return to a known same-module destination across area boundaries when an authored graph path exists, and the guard will require an appropriate waypoint or transition rather than fail incorrectly.
- **Backward compatibility:** Current direct-adjacent and same-area checks remain valid. Invalid destination protection remains fail-closed.
- **SP/MP compatibility:** Applies to runtime travel validation in both modes; tabletop scene follower coverage is included because the bug surfaced through a follower-led travel prompt.

## Review Notes

The minimal safe implementation likely uses the existing module location graph (`LocationGraph` or equivalent adjacency extraction) to answer: "Is destination reachable from current location within this module by authored edges?" It should not simply mark every `module_locations` entry safe, because that would allow unintended long-distance jumps inside a module.
