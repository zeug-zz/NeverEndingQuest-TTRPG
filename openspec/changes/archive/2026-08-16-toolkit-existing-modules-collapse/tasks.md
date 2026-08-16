## 1. Sidebar Structure and Styling

- [x] 1.1 Update `web/templates/module_toolkit.html` so each rendered module is a title-first, closed-by-default disclosure with the existing level, statistics, status, and download content in its detail body.
- [x] 1.2 Add the `Existing Modules` banner disclosure control and scoped CSS for ASCII `>` indicators, expanded state, focus visibility, compact title rows, and the existing scrollable sidebar layout.

## 2. Disclosure State Behavior

- [x] 2.1 Add page-session expansion state keyed by canonical module name, including state capture, refresh reapplication, and pruning for modules no longer present.
- [x] 2.2 Implement individual disclosure synchronization so open/closed state, indicator styling, and assistive-technology state remain aligned without changing other cards.
- [x] 2.3 Implement expand-all/collapse-all behavior for mixed, fully expanded, empty, and loading module lists, while preserving the existing module status and download actions.
  - Banner click wired via `setupExistingModulesToggle()` inside `setupModuleBuilderEventListeners()`; `toggleAllModules()` derives intent from the visible cards (`getVisibleModuleCards()`), opens every card when any is closed and closes every card when all are open, and is a safe no-op for empty/loading lists.
  - Bulk changes update `expandedModuleNames` synchronously per card via `syncModuleExpandedState()` (keyed by the `data-module-name` identity hook) so refresh behavior stays correct; queued native `toggle` events from the bulk flip remain idempotent no-ops.
  - Banner `aria-expanded`, `data-modules-banner-state`, label, and title are re-synced from the visible set by `syncModulesBannerState()` after individual toggles, bulk toggles, and every `module_list_response` render (including the two empty-list branches); no visible cards disables the control as a safe no-op.
  - Preserved existing level/status/detail content and `Download Adventure` behavior; no backend or payload changes.
  - Verification: provider-free DOM-stub suite against the real extracted handler logic (13/13 checks: loading/empty safety, mixed -> all open, all open -> all closed, individual toggle banner sync, refresh preserve/prune, content/action preservation); `node --check` on the extracted handler slice and full inline script; `git diff --check`; ASCII scan clean.

## 3. Regression Coverage

- [x] 3.1 Add provider-free source-contract tests for title-only initial rendering, individual disclosure controls, bulk disclosure behavior, refresh-state preservation, accessibility attributes, and legacy `module_builder.html` isolation.
  - `scripts/test_toolkit_existing_modules_collapse.py` (NEW, 31 tests, provider-free): reads `web/templates/module_toolkit.html` and `web/templates/module_builder.html` directly; no Flask, Socket.IO, browser, provider, or module fixtures.
  - Coverage: native `details`/`summary` card creation with no `open` attribute and title/indicator-only summary; level/status/download content ordered inside the detail body; per-card `toggle` listener sync via `syncModuleExpandedState()`/`syncModulesBannerState()` with `isConnected` guard; banner click wired to `toggleAllModules()` with visible-card intent derivation and empty-list no-op/disabled state; `expandedModuleNames` empty-set start, prune on refresh, conditional reapply, and banner resync on every render path; banner `aria-expanded`/`aria-controls`/`aria-label`/`data-modules-banner-state` contract, `aria-hidden` ASCII `>` indicators, and focus-visible CSS; legacy `module_builder.html` retains always-visible `div.module-item` cards with none of the new identifiers/hooks.
  - Verification: `.venv/bin/python -m unittest -q scripts.test_toolkit_existing_modules_collapse` -> 31/31 PASS; script entry point `.venv/bin/python scripts/test_toolkit_existing_modules_collapse.py` -> PASS; ASCII scan 0 violations.
- [x] 3.2 Verify the existing module-list payload fields, sidebar status markers, module ordering, and `Download Adventure` request contract remain present in the Toolkit template.
  - Added `TestExistingPayloadOrderingAndDownloadContract` (7 tests) to `scripts/test_toolkit_existing_modules_collapse.py`: `levelRange.min/max` rendering with `?` fallback, `areaCount`/`locationCount`/`plotPointCount` payload reads, `brief_failure` and `media_generator_needed` sidebar status markers, the `sortedModules` level-based comparator (`parseLevelValue` min then max then `moduleName.localeCompare`) feeding the render loop, and the `Download Adventure` button rendering `onclick="downloadAdventure('${module.moduleName}', this)"` wired to the existing `fetch(`/api/toolkit/modules/${moduleName}/adventure.md`)` request contract with `${moduleName}_adventure.md` download name.
  - Verification: `.venv/bin/python -m unittest -q scripts.test_toolkit_existing_modules_collapse` -> 38/38 PASS; `git diff --check` clean; ASCII scan 0 violations.

## 4. Verification

- [x] 4.1 Run JavaScript syntax validation for the updated Toolkit template and execute the focused Python regression suite with `.venv/bin/python`.
  - Inline script (lines 3007-9322) extracted to `tmp/module_toolkit_inline.js` -> `node --check` PASS; collapse-handler slice extracted to `tmp/module_toolkit_collapse_slice.js` -> `node --check` PASS; scratch files removed.
  - `.venv/bin/python -m unittest -q scripts.test_toolkit_existing_modules_collapse` -> Ran 38 tests, OK (38/38 PASS).
  - `git diff --check -- web/templates/module_toolkit.html scripts/test_toolkit_existing_modules_collapse.py openspec/changes/toolkit-existing-modules-collapse/tasks.md` -> exit 0, clean. Supplementary trailing-whitespace scan on the untracked test file and tasks.md -> 0 violations.
- [x] 4.2 Run ASCII compliance checks and perform a manual Toolkit smoke check covering initial collapse, individual toggle, mixed-state bulk toggle, empty-list handling, refresh behavior, and download action continuity.
  - ASCII: `python3 scripts/check_ascii_compliance.py --summary-only` -> 652 files scanned, 0 violations, exit 0 (run before and after scratch cleanup).
  - Provider-free smoke harness (`tmp/tt_collapse_smoke/`, removed after use) executed the REAL extracted collapse-handler slice (session set + per-card sync helpers + bulk toggle + `module_list_response` render loop) from `web/templates/module_toolkit.html` against a minimal DOM stub via Node 22: 20/20 checks PASS (initial render all closed/title-only + level-order preserved; individual open/close with banner resync; mixed bulk expands all with idempotent queued toggles; all-open bulk collapses all; empty/system-only/loading no-op safety with disabled banner; refresh reapplication, stale-name pruning, new modules closed; detached-node toggle ignored; expanded card retains level/area/location/plot counts, sidebar failure/handoff rows, and `downloadAdventure('${module.moduleName}', this)` action with fetch endpoint contract).
  - Focused suite: `.venv/bin/python -m unittest -q scripts.test_toolkit_existing_modules_collapse` -> Ran 38 tests, OK (38/38 PASS).
  - Scratch cleanup confirmed: `tmp/tt_collapse_smoke/` removed; no production code, tests, module data, or unrelated files modified.
