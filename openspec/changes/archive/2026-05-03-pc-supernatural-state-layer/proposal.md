# pc-supernatural-state-layer

## Why

PC `status` is currently the hard life/death field, but recent Thornwood/Vitreol play needs durable playable supernatural states such as corruption or undeath without overloading `status` or weakening dead-state stickiness.

This change formalizes a separate schema-valid supernatural-state layer so Python keeps enforcing mechanical reality while the narrator can interpret what kind of alive, dead, corrupted, or transformed thing a PC currently is.

## What Changes

- Add schema-valid PC fields for `creatureTypes` and `supernaturalStates`.
- Keep `status` normalization unchanged as the mechanical life-state axis: `alive`, `unconscious`, or `dead`.
- Replace ad-hoc `_supernatural_metadata` persistence from resurrection/corruption flows with durable `supernaturalStates` records.
- Project supernatural state summaries into Character Sheet, PDF, DM Note, conversation context, and combat truth context.
- Add tests proving playable undead/corrupted PCs remain mechanically active through `status: alive`, not `status: dead` or custom status values.
- Include a review-gated targeted Vitreol remediation task so the table can approve whether Vitreol is `humanoid + corrupted` or `undead + corrupted` before data is changed.

## Capabilities

### New Capabilities

- `pc-supernatural-state-schema`: Defines schema-valid creature type and durable supernatural state records for PCs while preserving life-state authority.
- `pc-supernatural-state-context-projection`: Defines where and how PC supernatural states are surfaced to players, prompts, validators, and exported sheets.

### Modified Capabilities

- `tt-resurrection-corruption-state-action`: Corrupted/undead resurrection consequences SHALL persist to schema-valid `supernaturalStates` instead of private `_supernatural_metadata`.

## Impact

Affected files likely include:

- `schemas/char_schema.json`
- `core/ai/action_handler.py`
- `utils/character_state_hygiene.py`
- `utils/pc_manager.py`
- `utils/multi_pc_dm_note.py`
- `core/ai/conversation_utils.py`
- `core/managers/combat_manager.py`
- `web/templates/game_interface.html`
- `web/routes/character_sheet_routes.py`
- focused regression tests under `scripts/`

Merge-safety impact:

- Host-file edits SHOULD be minimal and marked with `# TABLETOP MODE:` where they hook tabletop-specific projection behavior.
- The schema additions are additive and SHOULD remain backward compatible with existing character files.

SP/MP compatibility impact:

- Single-player behavior MUST remain valid because `status` semantics do not change.
- Multi-PC tabletop context gains additional state visibility but no automatic party/combat behavior changes unless existing systems read explicit state text.

Rollout risks:

- If mechanical effect strings are treated as automatically enforced rules, the runtime may imply unimplemented resistance/vulnerability logic. The first pass MUST treat them as explicit state descriptors unless deterministic effect handling is separately implemented.
- If Vitreol is remediated without review, the table could canonize the wrong creature-type axis. The Vitreol data patch is therefore review-gated.

Fallback:

- Existing character files with no `creatureTypes` or `supernaturalStates` continue to behave as ordinary living/dead PCs.
- If projection causes prompt bloat or validator loops, keep schema persistence and temporarily reduce prompt projection to concise badges only.
