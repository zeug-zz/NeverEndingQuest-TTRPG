# tt-resurrection-and-corruption-state-action

## Why

Once dead PCs are mechanically sticky, NEQ needs a safe explicit path for miracles, resurrection magic, corruption bargains, undead awakening, and similar high-drama outcomes. Generic HP updates are too ambiguous and dangerous for this role.

This change defines a future first-class state transition for resurrection and corruption. It should only be implemented after `tt-dead-pc-mechanical-stickiness` and `tt-supernatural-state-shape-contract` are reviewed.

## What Changes

- Add a dedicated action or structured operation for resurrection/corruption transitions.
- Only this explicit path MAY clear dead status and reset death-save failures.
- The transition MUST record source, mode, consequences, and whether the PC returns as ordinary living, corrupted, undead, or otherwise altered.
- Generic `updateCharacterInfo` HP/status edits MUST remain forbidden from reviving dead PCs.

## Non-Goals

- Do not implement this before death stickiness exists.
- Do not model full rules for every 5e resurrection spell in the first pass.
- Do not make resurrection automatically safe or consequence-free.
- Do not decide Vitreol's current canon state without user approval.

## Capabilities

- New capability: `tt-resurrection-corruption-state-action`

## Impact

Likely affected code:
- `core/ai/action_handler.py`
- `updates/update_character_info.py` or a new dedicated helper
- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- validation prompts if action validation is prompt-mediated
- focused tests under `scripts/`

Risks:
- Too much flexibility could reintroduce silent revival. The action must be narrow, explicit, and test-covered.

Fallback:
- Keep resurrection unavailable and require dead PCs to remain dead until the action validates.
