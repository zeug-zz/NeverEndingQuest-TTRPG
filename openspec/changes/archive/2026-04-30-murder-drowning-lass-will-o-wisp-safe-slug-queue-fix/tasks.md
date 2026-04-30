## 1. Backend MMG Asset Slug Alignment

- [x] 1.1 Update MMG unified asset monster extraction in `web/web_interface.py` to use runtime-safe slug normalization for dict monster references.
- [x] 1.2 Update MMG unified asset monster extraction in `web/web_interface.py` to use runtime-safe slug normalization for string monster references.
- [x] 1.3 Confirm `/api/toolkit/modules/Murder_at_the_Drowning_Lass/unified-assets` returns `id: "will_o_wisp"` for `Will-o'-Wisp` and does not return `will-o'-wisp`.

## 2. Backend MMG Generation And Report Hardening

- [x] 2.1 Re-normalize monster image target IDs server-side before compendium lookup, module monster lookup, `MonsterGenerator.generate_monster_image()`, copy destinations, progress emits, and failure records.
- [x] 2.2 Update `utils/module_media_generator_report.py` so monster asset audits normalize stale submitted IDs before checking module-local media.
- [x] 2.3 Confirm stale payload `{id: "will-o'-wisp", name: "Will-o'-Wisp"}` audits existing `will_o_wisp` media as present.

## 3. Frontend MMG Template Safety

- [x] 3.1 Harden `web/templates/module_toolkit.html` asset-row rendering so apostrophe-bearing display names do not break DOM IDs or inline JavaScript.
- [x] 3.2 Confirm the thumbnail container for `Will-o'-Wisp` renders as `asset-thumb-will_o_wisp`.
- [x] 3.3 Confirm clickable status controls and thumbnail clicks request media by safe asset id `will_o_wisp` while preserving display name `Will-o'-Wisp` in modal labels.

## 4. Regression Coverage

- [x] 4.1 Add MMG safe-slug regression coverage for `Will-o'-Wisp -> will_o_wisp` in unified asset discovery.
- [x] 4.2 Add MMG final media report coverage proving stale `will-o'-wisp` asset IDs resolve existing `will_o_wisp` image and thumbnail files.
- [x] 4.3 Add frontend source or DOM contract coverage proving apostrophe-bearing display names are escaped or handled without unsafe inline JavaScript breakage.
- [x] 4.4 Preserve existing validator coverage in `scripts/test_validator_monster_reference_hygiene.py`.

## 5. Verification

- [x] 5.1 Run `.venv/bin/python -m py_compile web/web_interface.py utils/module_media_generator_report.py`.
- [x] 5.2 Run targeted MMG safe-slug regression tests.
- [x] 5.3 Run `.venv/bin/python scripts/test_validator_monster_reference_hygiene.py`.
- [x] 5.4 Run `.venv/bin/python scripts/audit_module_gameplay.py --module Murder_at_the_Drowning_Lass --json` and confirm no missing base/thumb media for `will_o_wisp`.
- [x] 5.5 Verify the MMG UI or unified-assets response shows `Will-o'-Wisp` with `id: "will_o_wisp"`, `has_image: true`, and `has_thumbnail: true`.
- [x] 5.6 Run `openspec validate murder-drowning-lass-will-o-wisp-safe-slug`.
