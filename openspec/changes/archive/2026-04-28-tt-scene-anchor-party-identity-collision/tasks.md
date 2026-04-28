# Tasks

## 1. Guard API and canonical party identity

- [X] 1.1 Extend `evaluate_location_exclusivity_decision()` with optional `party_member_names`.
- [X] 1.2 Add a small canonicalization helper for party member name comparison.
- [X] 1.3 Preserve existing behavior when `party_member_names` is omitted or empty.

## 2. Exact bare-alias exemption

- [X] 2.1 Skip only off-location anchor aliases that exactly match a current party member canonical name.
- [X] 2.2 Continue to evaluate longer aliases and distinctive scene-state aliases for the same anchor.
- [X] 2.3 Ensure explicit transitions to anchor owner still allow distinctive aliases as before.

## 3. Runtime wiring

- [X] 3.1 Pass current `partyMembers` from `party_tracker_data` into the guard call in `main.py`.
- [X] 3.2 Keep diagnostic failure messages clear and fail-closed for non-exempt aliases.

## 4. Regression coverage

- [X] 4.1 Add a test where bare party member alias no longer fails.
- [X] 4.2 Add a test where distinctive alias still fails.
- [X] 4.3 Add a test proving existing off-location non-party anchor behavior still fails.
- [X] 4.4 Run `.venv/bin/python scripts/test_narrator_location_exclusivity_guards.py`.
- [X] 4.5 Run `openspec validate tt-scene-anchor-party-identity-collision`.
