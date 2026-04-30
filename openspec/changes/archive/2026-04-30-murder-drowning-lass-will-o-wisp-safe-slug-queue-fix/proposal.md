## Why

`Murder_at_the_Drowning_Lass` can still show `Will-o'-Wisp` as image `[FAIL]` in the Module Media Generator even after the safe media files exist as `will_o_wisp.jpg` and `will_o_wisp_thumb.jpg`.

The current regression is not a missing-media problem. The MMG unified asset scan still derives monster asset IDs with space-only replacement, so `Will-o'-Wisp` becomes `will-o'-wisp`; the template then looks for apostrophe-bearing filenames and renders DOM IDs such as `asset-thumb-will-o'-wisp`.

## What Changes

- Extend the existing Will-o'-Wisp safe-slug contract from validator/media files into the MMG asset scan, generation, report, and template paths.
- Normalize MMG monster asset IDs with the same runtime-safe slug rules used by `normalize_character_name()`.
- Re-normalize submitted monster asset IDs server-side before MMG image generation and final media report auditing.
- Harden MMG template rendering so asset IDs/names containing apostrophes cannot break inline handlers, DOM IDs, or media lookup behavior.
- Add regression coverage proving `Will-o'-Wisp` is exposed to the MMG frontend as `will_o_wisp` and resolves existing module-local media.

No breaking changes are intended.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `will-o-wisp-safe-slug`: Extend the safe-slug requirement to MMG unified asset discovery, MMG server-side media audit, MMG image generation inputs, and MMG frontend rendering.

## Impact

- Affected backend paths:
  - `web/web_interface.py` MMG unified asset scan and generation flow
  - `utils/module_media_generator_report.py` final MMG media report audit
- Affected frontend path:
  - `web/templates/module_toolkit.html` MMG asset table, thumbnail loading, and media click handlers
- Affected tests:
  - Add or extend MMG/toolkit regression coverage for safe monster slugs and apostrophe-bearing display names
- Merge safety:
  - Host-file changes SHOULD be small and marked with `# TABLETOP MODE:` where they alter upstream-adjacent behavior.
  - No changes to runtime combat loading, `ModulePathManager`, or canonical module media filenames are required.
- SP/MP compatibility:
  - This is toolkit/MMG behavior and does not alter single-player or tabletop runtime gameplay behavior.
- Provider behavior:
  - No LLM provider routing changes. Provider outage/quota behavior remains existing MMG fail-open/failure-record behavior.
