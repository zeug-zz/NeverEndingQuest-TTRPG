# Design: Sidebar Stale Media Report Guard

## Architecture Context

The `_derive_sidebar_audit_signals()` function in `core/generators/module_stitcher.py` has five logical phases:

```
Phase A (L1359-1389): Extract signals from build report (ready_status, publishable_status, remediation_categories)
Phase B (L1391-1446): Derive composite flags (has_build_failure, has_publication_blocker, media_generator_needed)
Phase C (L1448-1458): No-blocker fast path → check MMG report → potentially return clean
Phase D (L1460-1508): MMG report authoritative path → MMG can override/clear build report signals
Phase E (L1510-1525): brief_failure string mappings for remaining cases
```

The guard must be placed **between Phase B and Phase C** — right after `has_publication_blocker` is derived at line 1446. This ensures:

1. The stale flag is cleared BEFORE it routes the code into the failure paths of Phases C/D/E
2. The MMG report override logic in Phase D still runs first for the case where MMG is authoritative
3. The "fallback to build report when MMG is broken" behavior is preserved for `publishable_status == "fail"` scenarios

## Guard Location (Wrong vs. Right)

**WRONG placement (already applied, must revert):** Line 1389, right after `media_generator_needed` derivation.

Why wrong: This clears `media_generator_needed` before Phase D runs. If an MMG report exists (even malformed), the MMG fallback path (lines 1460-1508) can't use the build report's media debt as fallback information because the flag is already gone. This breaks tests 3-4 which validate MMG fallback.

**RIGHT placement:** After line 1446, after `has_publication_blocker` is derived.

```python
# Line 1446 (existing):
has_publication_blocker = media_generator_needed or publishable_status.startswith("fail")

# NEW guard:
# When publishability passes, media_generator_needed from stale
# remediation_categories is advisory/historical only. The
# publishable_status is the authoritative gate.
if media_generator_needed and publishable_status == "pass":
    media_generator_needed = False
    has_publication_blocker = False
```

Both `media_generator_needed` and `has_publication_blocker` MUST be cleared. If only `media_generator_needed` is cleared, `has_publication_blocker` stays True (from the stale value) and pushes into the failure path at line 1448 anyway.

## Test Impact Analysis

### Tests 1-2: Clean assertion change (publishable=pass, media debt)

These test that when `publishable_status="pass"` with media remediation categories, the sidebar shows the blocker. With the guard, the correct behavior is: publishability passes → no blocker. Assertions change from `assertEqual(brief_failure)` to `assertNotIn(brief_failure, entry)`.

### Tests 3-4: publishable_status change (fallback behavior)

These test "when MMG report is malformed/non-authoritative, fall back to build report media debt." The existing tests use `publishable_status="pass"` which contradicts the media debt. Fixed by changing to `publishable_status="fail"` — the guard won't trigger, and the MMG fallback logic still surfaces the media blocker from the build report. Assertions remain unchanged.

### All other tests: unaffected

The guard only triggers when `publishable_status == "pass"` AND `media_generator_needed == True`. All other tests use `publishable_status == "fail"` or have `media_generator_needed == False`.

## Report Refresh

Three modules need report refresh. Execute via `.venv/bin/python`:

```python
from web.extensions.toolkit_module_finisher import refresh_toolkit_build_report
for slug in ['Echoes_Of_Stone', 'Murder_at_the_Drowning_Lass', 'The_Hidden_City_of_Numillian']:
    result = refresh_toolkit_build_report(slug, refresh_reason="sidebar_unstale_media")
```

The refresh re-runs all deterministic audits. Since media now exists for all three modules, `structured_monster_media_missing` and `toolkit_manual_media_generation_required` will be dropped from `remediation_categories`, and `structural_media_debt_count` will reset to 0.
