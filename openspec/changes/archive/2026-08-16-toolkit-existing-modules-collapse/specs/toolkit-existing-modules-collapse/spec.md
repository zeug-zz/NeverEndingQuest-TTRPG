## Purpose

Provide a compact, accessible way to browse registered modules in the active Toolkit Module Builder sidebar without changing module data or backend behavior.

## ADDED Requirements

### Requirement: Module cards start collapsed

The active `/toolkit` Module Builder `Existing Modules` sidebar MUST render each valid registered module as a title-first card whose level range, statistics, status messages, and download action are hidden until that card is expanded.

#### Scenario: Initial module list is compact

- **WHEN** the active Toolkit Module Builder receives a non-empty module list for the first time in a page session
- **THEN** every rendered module card MUST be closed
- **AND** each closed card MUST show its module title and a visible `>` disclosure indicator
- **AND** the module details MUST NOT be visible

#### Scenario: Expanded card retains existing information

- **WHEN** a facilitator expands a module card
- **THEN** the card MUST show its existing level range, area count, location count, plot-point count, sidebar status messages, and `Download Adventure` action
- **AND** those values MUST come from the same module-list data as before this change

### Requirement: Individual module disclosure

Each module card MUST provide a keyboard-accessible disclosure control that toggles only that card between closed and expanded states.

#### Scenario: One module expands independently

- **WHEN** a facilitator activates the disclosure control for a closed module card
- **THEN** that card MUST expand
- **AND** other module cards MUST retain their current states
- **AND** the disclosure state MUST be exposed to assistive technology

#### Scenario: One module collapses independently

- **WHEN** a facilitator activates the disclosure control for an expanded module card
- **THEN** that card MUST close
- **AND** its detail content MUST no longer be visible
- **AND** other module cards MUST retain their current states

### Requirement: Expand or collapse all visible modules

The `Existing Modules` banner MUST provide a keyboard-accessible bulk disclosure control for the currently rendered module cards.

#### Scenario: Bulk control expands a mixed list

- **WHEN** at least one visible module card is closed and the facilitator activates the banner disclosure control
- **THEN** every visible module card MUST expand
- **AND** the banner control MUST expose that the visible set is expanded

#### Scenario: Bulk control collapses an expanded list

- **WHEN** every visible module card is expanded and the facilitator activates the banner disclosure control
- **THEN** every visible module card MUST close
- **AND** the banner control MUST expose that the visible set is collapsed

#### Scenario: Bulk control handles an empty list

- **WHEN** the module list contains no valid modules
- **THEN** activating the banner disclosure control MUST NOT throw an error
- **AND** the empty-list message MUST remain visible

### Requirement: Refresh preserves explicit session state

The sidebar MUST preserve explicit per-module expansion choices across client-side module-list refreshes during the current page session, keyed by the canonical module name.

#### Scenario: Existing expanded state survives refresh

- **GIVEN** a facilitator has expanded a registered module
- **WHEN** a later module-list response refreshes the sidebar and contains that same module
- **THEN** that module MUST be rendered expanded after the refresh

#### Scenario: New modules remain compact after refresh

- **GIVEN** a facilitator has expanded one or more existing modules
- **WHEN** a later module-list response adds a module that was not previously rendered
- **THEN** the new module MUST be rendered closed
- **AND** previously expanded modules MUST retain their states

### Requirement: Scope and compatibility boundaries

The collapsible behavior MUST be limited to the active `/toolkit` Module Builder sidebar and MUST NOT change the module-list payload, backend routes, module ordering, module status semantics, or the separate legacy `module_builder.html` page.

#### Scenario: Existing module actions remain compatible

- **WHEN** a facilitator expands a card and activates its existing download action
- **THEN** the same module-specific adventure download request MUST be made as before
- **AND** no module registry or persisted module state MUST be modified by disclosure interactions

#### Scenario: Legacy builder remains isolated

- **WHEN** a facilitator uses the standalone legacy builder page served from `module_builder.html`
- **THEN** this change MUST NOT alter that page's module-card rendering or behavior
