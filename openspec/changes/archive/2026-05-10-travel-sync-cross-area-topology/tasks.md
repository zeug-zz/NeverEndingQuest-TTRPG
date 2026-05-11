## 1. Topology Authority Helper

- [x] 1.1 Identify the smallest shared route-authority helper for same-module reachability, reusing `LocationGraph` behavior where practical.
- [x] 1.2 Ensure graph construction includes within-area `connectivity` / `connectedLocations` and cross-area `areaConnectivityId` edges.
- [x] 1.3 Keep direct adjacency and current-area membership checks as fast paths.
- [x] 1.4 Fail closed with compact diagnostics when graph construction or destination lookup fails.

**Verification for 1.1-1.4:** Unit tests prove `NC02 -> TW05` is reachable through authored topology and unknown destinations remain blocked.

## 2. Reconcile-First Guard Integration

- [x] 2.1 Wire same-module path reachability into `evaluate_travel_state_sync_decision(...)` or its topology helper.
- [x] 2.2 Preserve current rejection behavior for same-location no-ops, cross-module destinations, and no-route destinations.
- [x] 2.3 Ensure narration-only route planning does not require an action unless the response claims arrival or committed transition state.
- [x] 2.4 Preserve existing correction-note behavior on deterministic failures.

**Verification for 2.1-2.4:** Existing travel sync guard tests still pass, plus new cross-area tests cover valid path and invalid no-route cases.

## 3. Regression Coverage

- [x] 3.1 Add Thornwood regression fixture for `NC02 -> TW05` via `NC01` cross-area bridge.
- [x] 3.2 Add negative regression for a known same-module destination that is not reachable by authored graph from the current location.
- [x] 3.3 Add source-contract or behavior test proving the guard does not simply accept all `module_locations` entries.
- [x] 3.4 Add a scene follower travel prompt regression where a present follower can narratively guide toward a reachable cross-area destination without false `not topology-safe` failure.

**Verification for 3.1-3.4:** `.venv/bin/python scripts/test_travel_state_sync_guard.py` and any added focused tests pass.

## 4. Final Validation

- [x] 4.1 Run `.venv/bin/python -m py_compile utils/travel_state_sync_guard.py utils/authoritative_state_packet.py main.py` for touched files.
- [x] 4.2 Run `.venv/bin/python scripts/test_travel_state_sync_guard.py`.
- [x] 4.3 Run `.venv/bin/python scripts/test_scene_location_sync.py` if affected by shared topology behavior.
- [x] 4.4 Run `openspec validate travel-sync-cross-area-topology`.
