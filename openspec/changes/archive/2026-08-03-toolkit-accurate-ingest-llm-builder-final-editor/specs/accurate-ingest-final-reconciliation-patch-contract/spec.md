## ADDED Requirements

### Requirement: Final reconciliation patches SHALL be strictly validated before writes

The LLM Builder final editor SHALL return a strict JSON patch plan. Python SHALL validate the patch plan before any module file is written.

#### Scenario: Valid patch plan is accepted for application

- **GIVEN** the editor returns valid JSON with supported version, status, decisions, source-fidelity claim, publication intent, and file patches
- **AND** all file targets are listed in the brief editable surfaces
- **AND** all decision types are supported
- **WHEN** patch validation runs
- **THEN** the patch plan SHALL be eligible for application.

#### Scenario: Invalid JSON is rejected

- **GIVEN** the editor returns malformed JSON, freeform prose without parseable JSON, or a patch plan missing required keys
- **WHEN** patch validation runs
- **THEN** the build SHALL remain blocked
- **AND** no module file SHALL be modified.

#### Scenario: Forbidden file target is rejected

- **GIVEN** the editor patch plan targets a runtime-only file, an absolute path, a path outside the module directory, or a file not listed in editable surfaces
- **WHEN** patch validation runs
- **THEN** the patch SHALL be rejected
- **AND** no module file SHALL be modified.

#### Scenario: False clean source-fidelity claim is rejected

- **GIVEN** original source fidelity is blocked or degraded
- **AND** the editor patch plan claims `source_fidelity_status=pass` or equivalent clean-pass language
- **WHEN** patch validation runs
- **THEN** the system SHALL reject or normalize the claim to `source_fidelity_effective_status=reconciled_degraded`
- **AND** final reports SHALL NOT claim clean source-fidelity pass.
