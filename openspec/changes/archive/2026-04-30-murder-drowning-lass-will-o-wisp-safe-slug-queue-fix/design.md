## Overview

The previous safe-slug fix aligned validator and module media filenames around `will_o_wisp`. The remaining MMG failure comes from a separate slug path in the toolkit UI/backend: MMG asset discovery still converts monster names with only `lower().replace(' ', '_')`.

That leaves punctuation in the asset ID:

```text
Will-o'-Wisp -> will-o'-wisp
```

The rest of the module now uses the runtime-safe slug:

```text
Will-o'-Wisp -> will_o_wisp
```

## Contract Layer (MUST)

- MMG unified asset discovery MUST emit monster asset ID `will_o_wisp` for display name `Will-o'-Wisp`.
- MMG media status checks MUST look for `will_o_wisp.jpg` and `will_o_wisp_thumb.jpg`, not apostrophe-bearing filenames.
- MMG server-side generation MUST normalize submitted monster asset IDs before bestiary lookup, image generation, copy destination, progress events, and failure records.
- MMG final media reports MUST audit monster assets through runtime-safe IDs so stale browser payloads cannot produce false missing-media failures for `Will-o'-Wisp`.
- MMG frontend rendering MUST NOT embed raw apostrophe-bearing asset IDs or names in a way that breaks DOM IDs, inline JavaScript, or click handlers.
- Existing canonical media files MUST remain `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp.jpg` and `will_o_wisp_thumb.jpg`.
- `modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json` MUST remain the canonical monster JSON filename.

## Guidance Layer (SHOULD)

- Use `updates.update_character_info.normalize_character_name()` for MMG monster slug normalization instead of duplicating a near-match helper.
- Keep NPC canonicalization unchanged; this change targets monster asset IDs only.
- Prefer backend normalization over frontend-only repair so final reports and generation are correct even if stale browser state submits an old asset ID.
- Prefer DOM/event-listener hardening in `module_toolkit.html` over adding more inline quoted JavaScript where practical.
- If inline handlers remain, escape asset IDs and names with JSON-safe serialization before inserting them into HTML strings.

## Current Fault Path

1. `/api/toolkit/modules/<module>/unified-assets` scans area monsters.
2. `web/web_interface.py` builds `monster_id` using `monster['name'].lower().replace(' ', '_')`.
3. `Will-o'-Wisp` becomes `will-o'-wisp`.
4. The response payload sends `{id: "will-o'-wisp", name: "Will-o'-Wisp", type: "monster"}`.
5. `module_toolkit.html` renders `id="asset-thumb-will-o'-wisp"` and media URLs using `will-o'-wisp`.
6. Existing safe files are named `will_o_wisp.jpg` and `will_o_wisp_thumb.jpg`, so the UI shows `[FAIL]` / `?`.

## Proposed Implementation Shape

### Backend Unified Asset Scan

Update both dict and string monster-reference extraction in `get_module_unified_assets()` to use runtime normalization.

Expected behavior:

```text
Will-o'-Wisp -> will_o_wisp
Bob's Monster -> bob_s_monster
Hyphenated-Monster -> hyphenated_monster
```

### Backend MMG Image Generation

Before processing each monster image target, derive:

```text
raw_asset_id = asset.get('id')
raw_asset_name = asset.get('name') or raw_asset_id
asset_id = normalize_character_name(raw_asset_name or raw_asset_id)
asset_name = raw_asset_name or asset_id
```

Use the normalized `asset_id` for:

- compendium lookup
- module monster JSON lookup
- `MonsterGenerator.generate_monster_image(monster_id=...)`
- module media destination filenames
- progress event `asset_id`
- generation failure `asset_id`

### Final MMG Media Report

Normalize monster asset IDs in `utils/module_media_generator_report.py` before checking module-local media paths. This protects report correctness if the UI submits stale assets from a page loaded before the backend fix.

### Frontend Template Hardening

The frontend should treat `asset.id` as an opaque data value, not a safe HTML/JS literal. It should not directly interpolate raw IDs/names into inline handler strings without escaping.

Acceptable approaches:

- Render rows with `document.createElement()` and assign `dataset` values directly.
- Or serialize inline handler arguments using `JSON.stringify(...)`/equivalent escaping before HTML insertion.

## Risks And Fallback

- Risk: Changing monster ID derivation may alter MMG asset IDs for other punctuation-bearing monsters.
  - Mitigation: This aligns MMG with runtime and validator behavior; add regression coverage for apostrophe and hyphen cases.
- Risk: Stale browser state may submit old `will-o'-wisp` assets.
  - Mitigation: Server-side generation and report paths re-normalize submitted monster assets.
- Risk: Inline JavaScript escaping changes could affect MMG click handlers.
  - Mitigation: Add source-level or DOM-level regression coverage for apostrophe-bearing display names.
- Fallback: Existing module media and runtime gameplay are unaffected; if MMG generation fails, existing failure-record behavior remains in place.

## Verification Plan

- Run targeted MMG safe-slug regression tests.
- Run `.venv/bin/python scripts/test_validator_monster_reference_hygiene.py` to preserve the original validator contract.
- Run `.venv/bin/python scripts/audit_module_gameplay.py --module Murder_at_the_Drowning_Lass --json` and confirm base/thumb media remain present for `will_o_wisp`.
- If practical, exercise `/api/toolkit/modules/Murder_at_the_Drowning_Lass/unified-assets` and confirm the `Will-o'-Wisp` asset has `id: "will_o_wisp"`, `has_image: true`, and `has_thumbnail: true`.
