# Why

`Murder_at_the_Drowning_Lass` is still blocked in the module sidebar with `Publication blocked: missing media`, even though the Module Media Generator reports the module as complete.

The remaining blocker is not an MMG generation problem. It is a slug-contract mismatch for `Will-o'-Wisp`:

- Runtime and gameplay/media audits normalize `Will-o'-Wisp` to `will_o_wisp`.
- The monster JSON already exists as `modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json`.
- Existing media files are named with an apostrophe: `will-o'-wisp.jpg` and `will-o'-wisp_thumb.jpg`.
- `core/validation/validate_module_files.py` currently normalizes the name to `will_o__wisp` because it does not collapse consecutive underscores, so schema reference integrity expects the wrong JSON filename.

This produces a false schema/reference failure while the media tooling sees a different picture.

# What Changes

- Align validator monster-name normalization with runtime slug normalization.
- Keep `monsters/will_o_wisp.json` as the canonical monster JSON filename.
- Rename apostrophe-bearing media files to Win11-safe runtime slugs:
  - `media/monsters/will-o'-wisp.jpg` -> `media/monsters/will_o_wisp.jpg`
  - `media/monsters/will-o'-wisp_thumb.jpg` -> `media/monsters/will_o_wisp_thumb.jpg`
- Refresh `toolkit_build_report.json` for `Murder_at_the_Drowning_Lass` after validation and media audit pass.

# Capability Scope

- Validator slug normalization in `core/validation/validate_module_files.py`
- Module media filename cleanup under `modules/Murder_at_the_Drowning_Lass/media/monsters/`
- Regression coverage in `scripts/test_validator_monster_reference_hygiene.py`
- Report refresh for `Murder_at_the_Drowning_Lass`

# Non-Goals

- Do not rename `monsters/will_o_wisp.json` to `will_o__wisp.json`.
- Do not change `ModulePathManager`, `combat_builder`, or runtime combat slug lookup.
- Do not preserve apostrophe-bearing media filenames as canonical.
- Do not change MMG generation behavior beyond consuming safe filenames through existing slug rules.

# Impact

- Schema reference integrity resolves `Will-o'-Wisp` to the same file as runtime combat loading.
- Gameplay/media audit finds base and thumb media for `will_o_wisp`.
- `Murder_at_the_Drowning_Lass` should refresh to `ready_status=pass` and `publishable_status=pass`.
- Sidebar no longer shows a false missing-media blocker.

# Risk

- Low. The change narrows validator behavior to match existing runtime behavior. The JSON file is already named according to runtime rules.
