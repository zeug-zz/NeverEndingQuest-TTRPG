# Why

The sidebar's `_derive_sidebar_audit_signals()` derives `media_generator_needed` from `remediation_categories` in `toolkit_build_report.json`. These categories are additive/accumulative — they accumulate over multiple audit runs and are never pruned when conditions improve. The result: modules that pass publishability (`publishable_status: "pass"`) still show "Publication blocked: missing media" in the sidebar because stale `structured_monster_media_missing` entries persist in `remediation_categories`.

This is actively affecting Echoes_Of_Stone, Murder_at_the_Drowning_Lass, and The_Hidden_City_of_Numillian — all three have complete media but stale build reports.

The root cause is that `has_publication_blocker` and `media_generator_needed` are computed from `remediation_categories` without consulting `publishable_status`. The `publishable_status` is the authoritative audit gate — if it says "pass", any `media_generator_needed` derived from historical categories is advisory only, not blocking.

# What Changes

- Add a guard in `_derive_sidebar_audit_signals()` that clears `media_generator_needed` (and re-derives `has_publication_blocker`) when `publishable_status == "pass"`.
- Place the guard after all MMG report processing completes (after `has_publication_blocker` is computed at line 1446), not before. This preserves the "fallback to build report when MMG report is broken" behavior for non-passing modules.
- Refresh `toolkit_build_report.json` for the three affected modules.
- Update 4 sidebar tests to match the corrected semantics.

# Capability Scope

- Sidebar derivation in `core/generators/module_stitcher.py`
- Regression coverage in `scripts/test_module_sidebar_audit_failure_signals.py`
- Report refresh for Echoes_Of_Stone, Murder_at_the_Drowning_Lass, The_Hidden_City_of_Numillian

# Non-Goals

- Changing how `remediation_categories` is computed in the publishability audit
- Adding new MMG report generation
- Modifying the `remediation_categories` schema or pruning logic

# Impact

- Three modules lose their stale "Publication blocked: missing media" sidebar banner
- No real blockers are suppressed — only stale flags from passed audits are cleared
- Two test fixtures need `publishable_status` changed from "pass" to "fail" to preserve MMG fallback behavior testing

# Risks

- None. The guard only activates when `publishable_status == "pass"`, which is the authoritative "all checks passed" signal. Any legitimate media debt would have prevented the audit from passing.
