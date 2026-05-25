## ADDED Requirements

### Requirement: Brief Generator SHALL be runtime-output only

The brief generator SHALL write only inside the existing audit run directory and SHALL NOT mutate module artifacts.

#### Scenario: Outputs stay in audit run directory

- **GIVEN** an audit run directory outside `modules/<slug>/`
- **WHEN** the brief generator writes outputs
- **THEN** `builder_brief.json` and `builder_prompt_context.md` SHALL be written inside that audit run directory
- **AND** no files SHALL be written under `modules/<slug>/`.

#### Scenario: Module files are unchanged

- **GIVEN** module files before briefing
- **WHEN** the brief generator runs
- **THEN** module file hashes SHALL remain unchanged
- **AND** no module report artifact SHALL be refreshed.

### Requirement: Brief Generator SHALL not execute mutating workflows

The brief generator SHALL NOT call generation, repair, publication, or refresh workflows.

#### Scenario: No generation or refresh calls

- **GIVEN** a valid audit run
- **WHEN** the brief generator runs
- **THEN** it SHALL NOT call LLM providers, ModuleBuilder, seed writer, benchmark refresh, publishability refresh, readiness repair, media generation, or module finishing.
