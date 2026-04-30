## 1. Align Validator Slug Normalization

- [x] 1.1 Update `ModuleValidator._normalize_monster_name()` in `core/validation/validate_module_files.py` to match runtime `normalize_character_name()` semantics.
- [x] 1.2 Ensure apostrophes and hyphens normalize to a single collapsed underscore sequence.
- [x] 1.3 Ensure the function returns `will_o_wisp` for `Will-o'-Wisp`.

## 2. Rename Unsafe Media Files

- [x] 2.1 Rename `modules/Murder_at_the_Drowning_Lass/media/monsters/will-o'-wisp.jpg` to `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp.jpg`.
- [x] 2.2 Rename `modules/Murder_at_the_Drowning_Lass/media/monsters/will-o'-wisp_thumb.jpg` to `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp_thumb.jpg`.
- [x] 2.3 Confirm `modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json` remains unchanged.

## 3. Regression Coverage

- [x] 3.1 Update `scripts/test_validator_monster_reference_hygiene.py` so `Bob's Monster` expects `bob_s_monster`.
- [x] 3.2 Add normalization coverage proving `Will-o'-Wisp` normalizes to `will_o_wisp`.
- [x] 3.3 Add reference-integrity coverage proving an area monster named `Will-o'-Wisp` resolves to `monsters/will_o_wisp.json`.

## 4. Refresh Module Report

- [x] 4.1 Run `refresh_toolkit_build_report("Murder_at_the_Drowning_Lass", refresh_reason="will_o_wisp_safe_slug_fix")`.

## 5. Verification

- [x] 5.1 Run `.venv/bin/python -m py_compile core/validation/validate_module_files.py scripts/test_validator_monster_reference_hygiene.py`.
- [x] 5.2 Run `.venv/bin/python scripts/test_validator_monster_reference_hygiene.py`.
- [x] 5.3 Run `.venv/bin/python core/validation/validate_module_files.py --module Murder_at_the_Drowning_Lass --json` and confirm no `reference_integrity` failure.
- [x] 5.4 Run `.venv/bin/python scripts/audit_module_gameplay.py --module Murder_at_the_Drowning_Lass --json` and confirm no missing base/thumb media for `will_o_wisp`.
- [x] 5.5 Confirm refreshed `toolkit_build_report.json` has `ready_status=pass` and `publishable_status=pass`.
- [x] 5.6 Confirm module sidebar no longer shows `Publication blocked: missing media` for `Murder_at_the_Drowning_Lass`.
