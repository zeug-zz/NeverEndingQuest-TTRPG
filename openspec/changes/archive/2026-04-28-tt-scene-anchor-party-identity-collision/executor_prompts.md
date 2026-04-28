# Executor Prompts: tt-scene-anchor-party-identity-collision

## Execution Contract

MUST:
- Preserve location exclusivity for real off-location scene anchors.
- Exempt only exact bare aliases matching current party member identities.
- Continue blocking distinctive aliases like `corrupted Vitreol`, `Voidstone thrall`, and `vitreol_thrall` unless valid transition/movement state exists.
- Preserve behavior for callers that do not pass party identities.
- Use ASCII-only edits.

SHOULD:
- Keep helper functions local to `utils/narrator_location_exclusivity_guard.py` unless reuse is clearly needed.
- Prefer additive API changes with default `None` values.

## Prompt 1 - Guard API and Alias Filtering

Implement tasks 1.1 through 2.3 only.

Allowed files:
- `utils/narrator_location_exclusivity_guard.py`
- `scripts/test_narrator_location_exclusivity_guards.py`

Required behavior:
- Add optional `party_member_names` support.
- Build a canonical set of party member identities.
- For each off-location anchor alias, skip only exact canonical party-name aliases.
- Continue evaluating longer aliases and other aliases for the same anchor.
- Existing tests should pass without changes except where new assertions are added.

Forbidden scope:
- Do not modify module JSON data.
- Do not implement following scene entity state.

Edit Strategy:
- Apply one anchored patch around the public guard signature and metadata alias evaluation loop.
- Run `py_compile` after the guard change before editing tests.

Verification gate:
- `.venv/bin/python -m py_compile utils/narrator_location_exclusivity_guard.py scripts/test_narrator_location_exclusivity_guards.py`
- `.venv/bin/python scripts/test_narrator_location_exclusivity_guards.py`

Report:
- State which alias forms are exempt and which remain blocked.

## Prompt 2 - Runtime Wiring

Implement tasks 3.1 and 3.2 only.

Allowed files:
- `main.py`
- `scripts/test_narrator_location_exclusivity_guards.py` or existing source-contract tests if needed

Required behavior:
- Pass `party_tracker_data.get("partyMembers", [])` into the narrator location exclusivity guard.
- Preserve existing effective-location handling.
- Preserve current fail-closed messaging for non-exempt failures.

Forbidden scope:
- Do not restructure validation flow.
- Do not change NPC arrival validation.

Verification gate:
- `.venv/bin/python -m py_compile main.py`
- `.venv/bin/python scripts/test_narrator_location_exclusivity_guards.py`

Report:
- Mention exact callsite updated and any tests added.

## Prompt 3 - Final Verification

Complete tasks 4.1 through 4.5.

Verification gate:
- `.venv/bin/python -m py_compile utils/narrator_location_exclusivity_guard.py main.py scripts/test_narrator_location_exclusivity_guards.py`
- `.venv/bin/python scripts/test_narrator_location_exclusivity_guards.py`
- `openspec validate tt-scene-anchor-party-identity-collision`

Report:
- Summarize positive and negative guard scenarios.
