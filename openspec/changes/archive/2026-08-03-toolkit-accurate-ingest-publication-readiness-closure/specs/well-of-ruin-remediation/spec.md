## ADDED Requirements

### Requirement: Well_of_Ruin artifact SHALL pass all publishability audits after remediation

The existing Well_of_Ruin module SHALL be remediated deterministically so it passes all four previously-blocked audits without weakening any audit gate.

The remediation SHALL apply:
1. Continuity block in `module_context.json` (and BU mirror).
2. Semantic authority payload in `module_context.json` (and BU mirror).
3. Ingest sidecar in `modules/ingest/archive/`.
4. Placeholder JPEG media for all monster slugs missing base media.

#### Scenario: Remediation produces passing publishability audit

- **GIVEN** the current Well_of_Ruin module artifacts
- **WHEN** remediation is applied via the finalization helpers
- **THEN** `.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json` exits 0
- **AND** `ready_status` is `pass`
- **AND** `publishable_status` is `pass`

#### Scenario: Schema validation continues to pass

- **GIVEN** the remediated Well_of_Ruin module
- **WHEN** `.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin` runs
- **THEN** it exits 0 with 62/62 or better

#### Scenario: Sidecar audit passes

- **GIVEN** the remediated Well_of_Ruin module
- **WHEN** `.venv/bin/python scripts/homebrew_sidecar_audit.py --slug Well_of_Ruin --require-success` runs
- **THEN** it exits 0

### Requirement: Audit scripts remain unchanged

The remediation SHALL NOT modify any audit script: `audit_module_publishability.py`, `audit_module_gameplay.py`, `module_continuity_audit.py`, `module_semantic_authority_audit.py`, `homebrew_sidecar_audit.py`.

#### Scenario: No audit threshold changes

- **GIVEN** the remediated Well_of_Ruin module
- **WHEN** all audit scripts are diffed against the base branch
- **THEN** none of the five audit scripts listed above have been modified

### Requirement: BU mirror parity

If `module_context_BU.json` exists alongside `module_context.json`, the remediation SHALL apply continuity and semantic_authority changes to both files.

#### Scenario: BU mirror synced

- **GIVEN** Well_of_Ruin has `module_context_BU.json`
- **WHEN** remediation writes continuity and semantic_authority
- **THEN** both `module_context.json` and `module_context_BU.json` carry the new blocks
