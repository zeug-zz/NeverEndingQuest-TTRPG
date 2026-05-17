# toolkit-fidelity-review-payload Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-review-ui-fidelity-panel. Update Purpose after archive.
## Requirements
### Requirement: Fidelity review payload SHALL summarize accurate-ingest source fidelity artifacts

The toolkit SHALL expose a compact review payload built from existing accurate-ingest workspace artifacts before build approval.

#### Scenario: Clean fidelity payload is approvable

- **GIVEN** an accurate-ingest workspace has `normalization_fidelity_report.json` with clean or repaired status and no blockers
- **WHEN** the review payload is built
- **THEN** the payload SHALL include status, coverage counts, artifact paths, repair summary, blueprint status, and `can_approve: true`.

#### Scenario: Blocked fidelity payload is not approvable

- **GIVEN** an accurate-ingest workspace has blocked or failed fidelity status
- **WHEN** the review payload is built
- **THEN** the payload SHALL include compact blocker findings
- **AND** it SHALL set `can_approve: false` with a refusal reason.

#### Scenario: Missing accurate-ingest artifact fails closed

- **GIVEN** source/fidelity evidence indicates accurate-ingest mode
- **AND** required fidelity review artifacts are missing or malformed
- **WHEN** the review payload is built
- **THEN** the payload SHALL fail closed with `can_approve: false`
- **AND** it SHALL identify the missing or malformed artifact.

### Requirement: Legacy workspaces SHALL not require fidelity review payloads

The toolkit SHALL preserve legacy behavior for workspaces that do not carry accurate-ingest source/fidelity artifacts.

#### Scenario: Legacy workspace is classified as legacy

- **GIVEN** a workspace lacks source graph, fidelity report, repair attempts, and blueprint artifacts
- **WHEN** fidelity review payload generation runs
- **THEN** the payload SHALL identify mode `legacy`
- **AND** missing accurate-ingest artifacts SHALL NOT block legacy behavior.

