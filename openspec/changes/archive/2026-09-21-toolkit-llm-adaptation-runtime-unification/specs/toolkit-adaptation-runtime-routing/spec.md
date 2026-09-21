## Purpose

Defines how the completed adaptation contracts become the background build route for eligible Toolkit inputs while preserving an explicit, unchanged legacy route when adaptation is disabled.

## ADDED Requirements

### Requirement: Enabled adaptation routes eligible Toolkit inputs

When `ENABLE_LLM_ADAPTATION` is exactly `True`, the Toolkit SHALL route eligible uploaded adventure sources and text-description builds through the adaptation pipeline without requiring a separate GUI mode selection.

#### Scenario: Uploaded adventure uses adaptation by default

- **WHEN** an approved Markdown or PDF adventure upload is accepted and adaptation is enabled
- **THEN** the job SHALL select the adaptation route before packet building
- **AND** SHALL preserve the upload source hash, source kind, rights classification, and attempt identity

#### Scenario: Text description uses adaptation by default

- **WHEN** a valid module name and text description are submitted through the existing Toolkit builder and adaptation is enabled
- **THEN** the build SHALL select the adaptation route before ModuleBuilder writes a module
- **AND** SHALL treat the submitted description as bounded user-authored source context

### Requirement: Disabled adaptation preserves legacy behavior

When `ENABLE_LLM_ADAPTATION` is missing, invalid, or exactly `False`, the Toolkit SHALL preserve the existing legacy accurate-ingest and text-description builder routes without requiring adaptation artifacts.

#### Scenario: Upload with adaptation disabled

- **WHEN** an approved adventure upload is built while adaptation is disabled
- **THEN** the existing accurate-ingest packet path SHALL remain selectable
- **AND** no adaptation author request or adaptation dossier SHALL be required

#### Scenario: Text build with adaptation disabled

- **WHEN** a text-description build is started while adaptation is disabled
- **THEN** the existing direct builder behavior SHALL remain available
- **AND** existing readiness and finishing gates SHALL continue to apply

### Requirement: No additional GUI mode is required

The background adaptation route SHALL reuse the existing upload, review, build, progress, and result interactions; the Toolkit SHALL NOT require a new adaptation selector or a second user-facing build workflow.

#### Scenario: Existing upload controls remain sufficient

- **WHEN** an operator uploads an eligible source with adaptation enabled
- **THEN** the existing upload and build controls SHALL start the adaptation route
- **AND** the operator SHALL receive the existing bounded progress and terminal status surfaces

### Requirement: Selected adaptation failures do not silently downgrade

Once an eligible build has selected the adaptation route, authoring, provider, dossier, staging, validation, or publication failure SHALL produce an explicit adaptation failure or blocked outcome and SHALL NOT silently restart through legacy generation.

#### Scenario: Adaptation author refuses

- **WHEN** the selected adaptation author returns a refusal
- **THEN** the job SHALL terminate with an adaptation authoring/refusal diagnostic
- **AND** SHALL not create a completed module or registry entry

#### Scenario: Adaptation infrastructure failure

- **WHEN** the selected adaptation route encounters a timeout, quota, dependency, or provider failure
- **THEN** the job SHALL expose an infrastructure failure outcome
- **AND** SHALL not consume the semantic revision budget or silently use legacy generation
