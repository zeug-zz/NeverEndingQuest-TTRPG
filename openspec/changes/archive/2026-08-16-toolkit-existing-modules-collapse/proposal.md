## Why

The active Module Toolkit builder tab renders every registered module as a fully expanded card. With several modules installed, the right-hand `Existing Modules` panel becomes difficult to scan and consumes unnecessary vertical space before the facilitator has selected a module to inspect.

The objective is to make the sidebar title-first: all module cards start collapsed, individual cards can be opened with a `>` control, and the panel header can expand or collapse the complete visible list.

## What Changes

- Add a collapsed title row for every module in the active `/toolkit` Module Builder tab.
- Hide level information, statistics, status messages, and the download action until an individual module is expanded.
- Add an individual `>` disclosure control for each module and expose its expanded state to assistive technology.
- Add a `>` control to the `Existing Modules` banner that expands all modules when any are closed and collapses all modules when all are open.
- Keep the initial state collapsed and preserve explicit per-module expansion choices across client-side module-list refreshes during the current page session.
- Keep module names, sidebar status signals, and `Download Adventure` behavior unchanged when a card is expanded.
- Add provider-free UI contract coverage and JavaScript syntax verification.

### Non-goals

- Do not change the module-list socket payload, backend routes, registry data, or module ordering.
- Do not persist expansion preferences in local storage or campaign state.
- Do not change the separate legacy standalone builder served by `module_builder.html`.
- Do not alter module publication, media, readiness, or sidebar audit semantics.

## Capabilities

### New Capabilities

- `toolkit-existing-modules-collapse`: Title-first collapsible module cards and expand/collapse-all controls for the active Toolkit Module Builder sidebar.

### Modified Capabilities

None. Existing sidebar status and download requirements remain unchanged.

## Impact

- **Affected UI:** `web/templates/module_toolkit.html` markup, styles, and client-side module-list rendering.
- **Affected verification:** Source-contract tests for the Toolkit template and JavaScript syntax checks.
- **Unaffected systems:** Backend APIs, Socket.IO payloads, module registry state, LLM/provider routing, and module data files.
- **Merge safety:** The change is confined to one existing host template with no Python or schema changes. Any host-template modifications SHOULD remain minimal and clearly scoped to the Toolkit sidebar.
- **SP/MP compatibility:** The Toolkit page is independent of gameplay mode; single-player and TABLETOP MODE runtime behavior are unchanged.
- **Rollout risk and fallback:** Risk is limited to client-side disclosure state and list rerender behavior. Native/default-closed disclosure behavior SHOULD remain usable if the optional bulk-toggle script fails. If the feature causes a regression, removing the new sidebar markup and style/script hooks restores the existing always-expanded cards without affecting persisted module state.
