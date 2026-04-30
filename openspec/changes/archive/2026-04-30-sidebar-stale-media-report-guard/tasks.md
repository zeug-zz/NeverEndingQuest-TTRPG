## 1. Revert incorrect guard and place correct guard

- [X] 1.1 Remove the guard prematurely added at line 1389 in `core/generators/module_stitcher.py` (between `media_debt_count` and `media_generator_needed` derivation). Restore the original code block.
- [X] 1.2 Add the correct guard after `has_publication_blocker` derivation (after current line 1446). The guard must clear both `media_generator_needed` and `has_publication_blocker` when `publishable_status == "pass"`.

## 2. Update sidebar regression tests

- [X] 2.1 In `test_media_only_debt_surfaces_publication_blocker` (line ~178): Change assertions from `assertEqual(brief_failure, "Publication blocked: missing media")` and `assertTrue(media_generator_needed)` to `assertNotIn("brief_failure", entry)` and `assertNotIn("media_generator_needed", entry)`.
- [X] 2.2 In `test_degraded_authoritative_final_media_only_report_surfaces_handoff` (line ~196): Same assertion changes as 2.1.
- [X] 2.3 In `test_malformed_mmg_report_falls_back_to_build_report_media_debt` (line ~399): Change `publishable_status="pass"` to `publishable_status="fail"`. Keep existing assertions unchanged.
- [X] 2.4 In `test_non_authoritative_mmg_report_falls_back_to_build_report_media_debt` (line ~421): Change `publishable_status="pass"` to `publishable_status="fail"`. Keep existing assertions unchanged.

## 3. Refresh stale module build reports

- [X] 3.1 Run `refresh_toolkit_build_report()` for `Echoes_Of_Stone`.
- [X] 3.2 Run `refresh_toolkit_build_report()` for `Murder_at_the_Drowning_Lass`.
- [X] 3.3 Run `refresh_toolkit_build_report()` for `The_Hidden_City_of_Numillian`.

## 4. Verification

- [X] 4.1 Compile-check: `.venv/bin/python -m py_compile core/generators/module_stitcher.py` passes.
- [X] 4.2 Test suite: `.venv/bin/python scripts/test_module_sidebar_audit_failure_signals.py` — all 17 tests pass.
- [X] 4.3 Confirm refreshed reports have `report_freshness.state: "current"` and `remediation_categories` no longer contain `structured_monster_media_missing` or `toolkit_manual_media_generation_required`.
