# Design

## Verified Current State

The module currently has:

```text
modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json
modules/Murder_at_the_Drowning_Lass/media/monsters/will-o'-wisp.jpg
modules/Murder_at_the_Drowning_Lass/media/monsters/will-o'-wisp_thumb.jpg
```

`WM001.json` and `WM001_BU.json` reference the display name `Will-o'-Wisp` in both structured location monster content and prose encounter text.

The current validator error is:

```text
Will-o'-Wisp in The Widdershins Moors/Witchlight Standing Stone -> expected monsters/will_o__wisp.json
```

This is inconsistent with runtime. Runtime uses `updates.update_character_info.normalize_character_name()` through `ModulePathManager.get_monster_path()`, which collapses consecutive underscores and resolves `Will-o'-Wisp` to `will_o_wisp`.

## Slug Contracts

### Runtime Contract

Runtime slug path:

```text
ModulePathManager.get_monster_path()
  -> format_filename()
  -> updates.update_character_info.normalize_character_name()
```

Effective result:

```text
Will-o'-Wisp -> will_o_wisp
```

### Gameplay/Media Audit Contract

`scripts/audit_module_gameplay.py:normalize_slug()` also collapses repeated underscores:

```text
Will-o'-Wisp -> will_o_wisp
```

This is why the gameplay/media audit expects:

```text
modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp.jpg
modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp_thumb.jpg
```

### Validator Contract (Current Bug)

`core/validation/validate_module_files.py:_normalize_monster_name()` replaces apostrophes and hyphens with underscores but does not collapse repeated underscores:

```text
Will-o'-Wisp -> will_o__wisp
```

This is the outlier and should be fixed.

## Implementation Details

### Validator Normalization

Preferred implementation:

```python
@staticmethod
def _normalize_monster_name(name):
    """Normalize monster name to slug format used by runtime loaders."""
    if not name:
        return ""
    from updates.update_character_info import normalize_character_name
    return normalize_character_name(str(name))
```

If the builder wants to avoid importing from `updates` inside validation, duplicate the runtime logic exactly:

```python
slug = str(name or "").strip().lower()
slug = slug.replace(" ", "_")
slug = slug.replace("'", "_")
slug = re.sub(r"[^a-z0-9_]", "_", slug)
slug = re.sub(r"_+", "_", slug).strip("_")
return slug
```

Either implementation MUST produce:

```text
Will-o'-Wisp -> will_o_wisp
Bob's Monster -> bob_s_monster
Hyphenated-Monster -> hyphenated_monster
```

### Media Renames

Rename only the media files:

```text
modules/Murder_at_the_Drowning_Lass/media/monsters/will-o'-wisp.jpg
  -> modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp.jpg

modules/Murder_at_the_Drowning_Lass/media/monsters/will-o'-wisp_thumb.jpg
  -> modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp_thumb.jpg
```

Do not rename:

```text
modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json
```

It already matches runtime and gameplay/media audit slug rules.

## Report Refresh

After implementation and local validation, refresh the module report:

```python
from web.extensions.toolkit_module_finisher import refresh_toolkit_build_report
refresh_toolkit_build_report(
    "Murder_at_the_Drowning_Lass",
    refresh_reason="will_o_wisp_safe_slug_fix",
)
```

Expected result:

```text
ready_status=pass
publishable_status=pass
```

## Interaction With Sidebar Guard

This change should make the media debt resolve naturally for `Murder_at_the_Drowning_Lass`. The separate `sidebar-stale-media-report-guard` remains useful for reports that carry historical remediation categories after `publishable_status=pass`, but this change should remove the real readiness failure for Murder.
