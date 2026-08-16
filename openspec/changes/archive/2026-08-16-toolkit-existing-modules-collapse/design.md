## Context

The active `/toolkit` page renders `module_toolkit.html`. Its `module_list_response` handler clears and rebuilds `#modules-list` whenever module data is refreshed, while the backend payload already contains all values needed by the existing cards. The separate standalone builder uses `module_builder.html` and is intentionally outside this change.

See `proposal.md` for the motivation and scope.

## Goals / Non-Goals

**Goals:**

- Make the active module sidebar title-first and collapsed by default.
- Preserve the existing module detail content and download behavior.
- Provide accessible individual and bulk disclosure controls.
- Keep explicit expansion choices stable across client-side list refreshes.
- Keep the implementation limited to the existing Toolkit template and provider-free regression coverage.

**Non-Goals:**

- No backend, Socket.IO payload, module registry, or persistence changes.
- No local-storage preference or campaign-state persistence.
- No changes to the legacy standalone builder.
- No changes to sidebar audit, readiness, publication, or media status calculation.

## Decisions

### Use native disclosure semantics for individual cards

The module card SHOULD use native `details`/`summary` disclosure semantics, with the summary containing the visible `>` indicator and module title. This supplies keyboard interaction and default-closed behavior without making individual-card usability depend on custom JavaScript.

The alternative is a `div` card with custom buttons and `display` state managed entirely by JavaScript. That approach would require more event handling and could make the detail content inaccessible if a script error occurs, so it is not preferred.

### Keep expansion state in page-session JavaScript

The renderer SHOULD maintain a small in-memory set of expanded canonical module names. The set starts empty, updates when an individual card changes state, and is reapplied when a refreshed module list is rendered. Entries for modules no longer present SHOULD be pruned.

No local storage or runtime file is appropriate because disclosure state is a temporary viewing preference and must not become campaign or module data.

### Derive the banner state from visible cards

The banner control SHOULD inspect the currently rendered cards rather than maintain an independent authoritative `all expanded` flag. If any visible card is closed, the next bulk action opens all visible cards; if all visible cards are open, it closes all of them. The banner's `aria-expanded`, label, and visual indicator SHOULD be updated after individual, bulk, and refresh operations.

An empty or loading list is a no-op for bulk behavior and MUST not produce a client-side exception.

### Preserve the existing detail body

The existing level, counts, status indicators, and download button SHOULD remain in the existing detail container. Only their visibility and the surrounding title/disclosure structure change. No module payload fields or backend calls are added.

### Keep visual indicators ASCII-compatible

The disclosure indicator SHOULD use the ASCII `>` character and CSS state styling rather than introducing Unicode glyphs. Focus styling MUST remain visible against the existing dark Toolkit palette.

## Risks / Trade-offs

- **[Risk] Socket refreshes can discard DOM state.** -> Reapply the in-memory expanded-name set after every module-list render and close modules that are newly introduced.
- **[Risk] Bulk and individual controls can expose stale `aria-expanded` values.** -> Centralize state synchronization after every state change and refresh.
- **[Risk] Existing inline download behavior could be affected by new disclosure markup.** -> Keep the download action inside the detail body and add a regression assertion for its existing endpoint/template.
- **[Risk] CSS changes could make details unreadable on narrow sidebars.** -> Preserve the current scrollable panel, use the existing card width, and verify both closed and expanded states at the Toolkit sidebar width.
- **[Trade-off] Native disclosure semantics reduce custom code but constrain the card structure.** -> Keep the summary limited to the title and indicator; retain all interactive actions in the detail body.

## Migration Plan

1. Add the disclosure markup, scoped CSS, and client-side state synchronization to `web/templates/module_toolkit.html`.
2. Add provider-free source-contract tests for the collapsed default, individual toggle, bulk toggle, refresh-state preservation, accessibility attributes, and legacy-template isolation.
3. Run JavaScript syntax checking and the focused Python regression suites.
4. If verification or manual smoke testing finds a regression, remove the new template hooks and restore the previous always-expanded card structure. No persisted data migration or rollback is required.
