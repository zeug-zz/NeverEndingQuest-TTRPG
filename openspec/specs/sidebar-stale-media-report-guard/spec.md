# sidebar-stale-media-report-guard Specification

## Purpose
TBD - created by archiving change sidebar-stale-media-report-guard. Update Purpose after archive.
## Requirements
### Requirement: Sidebar suppresses stale media blockers when publishability passes

`core/generators/module_stitcher.py` SHALL treat `publishable_status == "pass"` as authoritative for publication gating and SHALL NOT surface a media blocker solely from historical `remediation_categories`.

Specifically, in `_derive_sidebar_audit_signals(...)`, when `media_generator_needed` is true due to stale category carryover and `publishable_status == "pass"`, the function MUST clear `media_generator_needed` and clear `has_publication_blocker` before choosing failure messaging.

#### Scenario: Publishable module with stale media remediation categories

**Given** a persisted `toolkit_build_report.json` with `publishable_status: "pass"`  
**And** `remediation_categories` containing `"structured_monster_media_missing"` and/or `"toolkit_manual_media_generation_required"`  
**When** `_derive_sidebar_audit_signals(...)` computes sidebar state  
**Then** the module entry SHALL NOT contain `brief_failure`  
**And** the module entry SHALL NOT contain `media_generator_needed`

### Requirement: MMG fallback behavior remains for non-passing publishability

When publishability does not pass, malformed or non-authoritative MMG reports SHALL continue to fall back to build-report media debt logic.

#### Scenario: MMG malformed and publishability fail

**Given** a persisted build report with `publishable_status: "fail"` and media debt categories  
**And** a malformed `module_media_generator_report.json`  
**When** `_derive_sidebar_audit_signals(...)` computes sidebar state  
**Then** the module entry SHALL contain `brief_failure: "Publication blocked: missing media"`  
**And** the module entry SHALL contain `media_generator_needed: true`

### Requirement: Refresh path supports stale sidebar correction without MMG rerun

`refresh_toolkit_build_report(...)` SHALL remain a valid non-MMG path to regenerate authoritative sidebar-facing report state.

#### Scenario: Refresh clears stale sidebar media blocker

**Given** a module with complete media files but stale persisted remediation categories  
**When** `refresh_toolkit_build_report(module_slug)` is executed  
**Then** the resulting sidebar derivation SHALL not display `Publication blocked: missing media` for that module when `publishable_status` is pass

