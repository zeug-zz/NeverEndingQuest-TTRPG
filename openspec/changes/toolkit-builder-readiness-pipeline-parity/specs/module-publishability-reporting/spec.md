## ADDED Requirements

### Requirement: Publishability reports SHALL preserve readiness convergence outcome
Publication-facing reports for toolkit-built modules SHALL preserve readiness convergence outcome separately from final publishability status.

#### Scenario: Readiness fails before publishability
- **WHEN** a legacy builder run fails readiness convergence before final finishing
- **THEN** the user-facing result SHALL identify readiness as the failing phase
- **AND** it SHALL include convergence details or a path to persisted convergence details
- **AND** it SHALL not present the failure as a semantic publishability blocker unless publishability actually ran.

#### Scenario: Readiness passes but publishability fails
- **WHEN** readiness convergence passes and final publishability fails
- **THEN** the final report SHALL show `ready_status: "pass"`
- **AND** it SHALL show a non-passing `publishable_status`
- **AND** it SHALL preserve semantic/media blocker details from publishability reporting.

#### Scenario: Media handoff remains distinct from readiness failure
- **WHEN** readiness passes and publishability detects only eligible media-only debt
- **THEN** the report SHALL preserve success-with-media-handoff semantics
- **AND** it SHALL direct the user to Module Builder -> Module Media Generator
- **AND** it SHALL not label the build as readiness failure.

### Requirement: Builder completion payload SHALL expose final statuses
The legacy builder socket completion/error payloads SHALL expose machine-readable final statuses that match persisted report semantics.

#### Scenario: Publishable success payload
- **WHEN** a legacy builder run passes readiness and publishability
- **THEN** the completion payload SHALL include final status fields indicating readiness passed and publishability passed.

#### Scenario: Non-publishable payload
- **WHEN** a legacy builder run passes readiness but fails publishability
- **THEN** the payload SHALL include final status fields indicating readiness passed and publishability failed
- **AND** the UI SHALL render remediation details instead of a generic build failure only.
