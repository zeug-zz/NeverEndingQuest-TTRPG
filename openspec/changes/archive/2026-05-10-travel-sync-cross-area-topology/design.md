## Context

`travel_state_sync_guard.evaluate_travel_state_sync_decision(...)` currently receives both a full module location catalog and area-scoped reachable IDs. The safety helper only checks direct adjacency plus current-area membership. Cross-area bridges authored with `areaConnectivityId` are therefore invisible to the reconcile-first guard.

`utils/location_path_finder.py` already builds a richer same-module graph from location connectivity plus external area connections. The implementation should prefer reusing that existing graph behavior or extracting the same adjacency rules into a shared helper, rather than creating a second partial topology model.

## Contract Layer (MUST)

- Reconcile-first travel validation MUST recognize authored same-module paths that cross area boundaries.
- Cross-area reachability MUST be based on authored topology (`connectivity`, `connectedLocations`, `areaConnectivityId`, or the existing `LocationGraph` equivalent), not conversation history alone.
- The guard MUST continue to reject unknown destination names or IDs.
- The guard MUST continue to reject destinations in other modules unless handled by explicit cross-module tracker flow.
- The guard MUST continue to reject same-location no-op transitions.
- The guard MUST NOT treat every known module location as automatically topology-safe.
- The implementation MUST preserve deterministic correction messages when a destination is not topology-safe.
- The implementation MUST remain fail-closed if topology graph construction fails.
- Python user-facing console/log text introduced by implementation MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Prefer a shared helper such as `is_same_module_path_reachable(module_name, current_location_id, destination_id)` so explicit transition validation and reconcile-first validation can converge over time.
- Preserve direct-adjacent and same-area behavior as fast checks before graph traversal.
- Include bounded diagnostics for rejected destinations: current location, destination ID/name, and whether graph lookup failed or no route exists.
- Keep route selection as narrator-facing prose; Python only validates whether a destination is reachable, not which exact path must be narrated.

## Thornwood Example

The authored route from `NC02` to `TW05` is valid through an intermediate cross-area bridge:

- `NC02` (Blighted Thornbriar Grove) -> `NC01` (Corrupted Entry Cave) via `connectivity`
- `NC01` -> `TW05` (Bandit Stronghold) via `areaConnectivityId`

The guard should allow a narrator response that frames travel toward `TW05` when it is grounded in this authored path, while still allowing the narrator to stage the next waypoint (`NC04`, `NC01`, etc.) if it chooses.

## Degraded Behavior

- If the graph cannot be built, the guard should preserve the current fail-closed behavior and report the destination as not topology-safe with an internal diagnostic.
- If the destination resolves to a module location but no authored path exists from the current location, the guard should continue rejecting it.
- If the model emits narration-only route planning with no committed arrival or transition, validation may remain narration-only provided it does not claim arrival at an unsafe destination.

## Rollback

Rollback is straightforward: restore the current `_is_topology_safe_destination(...)` behavior. The change should not mutate module data or persisted game state.
