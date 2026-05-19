## ADDED Requirements

### Requirement: Legacy Numillian v1 SHALL remain non-production

The legacy inaccurate Numillian module, if present, SHALL remain archive/comparison content and SHALL NOT replace the production module.

#### Scenario: v1 is present as archive only

- **GIVEN** `modules/The_Hidden_City_of_Numillian_v1/` exists
- **WHEN** module registration and publication state are inspected
- **THEN** v1 SHALL be documented or treated as archive/comparison only
- **AND** v1 SHALL NOT be registered as the current production `The_Hidden_City_of_Numillian` module.

#### Scenario: v1 is absent

- **GIVEN** `modules/The_Hidden_City_of_Numillian_v1/` is absent
- **WHEN** production Numillian is verified
- **THEN** absence of v1 SHALL NOT block publication proof if production artifacts are source-faithful.

#### Scenario: v1 is not a repair source

- **GIVEN** production Numillian has missing source content
- **WHEN** remediation is performed
- **THEN** remediation SHALL use source markdown or deterministic accurate-ingest artifacts
- **AND** SHALL NOT restore v1 content as the primary production fix without a future explicit change.

### Requirement: Production identity SHALL remain unambiguous

Normal module selection and publication surfaces SHALL identify the production module unambiguously.

#### Scenario: Production slug is selected

- **GIVEN** module discovery, public catalog, or README listing references Numillian
- **WHEN** a user selects the production module
- **THEN** the selected slug SHALL resolve to `The_Hidden_City_of_Numillian`
- **AND** SHALL NOT silently resolve to `The_Hidden_City_of_Numillian_v1`.
