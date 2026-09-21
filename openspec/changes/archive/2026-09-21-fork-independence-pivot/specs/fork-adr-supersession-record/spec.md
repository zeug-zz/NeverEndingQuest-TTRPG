## Purpose

Define the durable ADR record for the independent fork decision: ADR-0031
exists and is discoverable, superseded ADRs preserve their historical
rationale, ADR-0003 is rescoped to internal extension discipline, and the ADR
index and supersession map stay consistent with each ADR's metadata.

## ADDED Requirements

### Requirement: ADR-0031 records the independent fork decision

The repository SHALL provide `adrs/0031-independent-development-fork.md` with
status `Accepted`, `Supersedes: ADR-0002 and ADR-0030`, and sections covering:
context, decision, retained internal boundaries, remote policy, attribution and
license policy, React vendor policy, and marker policy.

#### Scenario: Required ADR metadata and decision content

- **WHEN** reading `adrs/0031-independent-development-fork.md`
- **THEN** the metadata SHALL include `Status: Accepted`
- **AND** the metadata SHALL record that it supersedes ADR-0002 and ADR-0030
- **AND** the decision body SHALL state that the fork develops independently,
  that upstream is historical reference only, and that ports require separately
  approved fork changes
- **AND** the body SHALL record the remote policy, the Fair Source and
  attribution obligations, the React one-time vendor policy, and the marker
  policy as fork lineage documentation

#### Scenario: ADR discoverability

- **WHEN** a maintainer reads `adrs/index.md`
- **THEN** ADR-0031 SHALL be listed with its title and `Accepted` status

### Requirement: Superseded ADRs preserve historical rationale

ADR-0002 and ADR-0030 SHALL be marked `Superseded` with
`Superseded by: ADR-0031`, and their original context, decision, and
consequence text SHALL remain present.

#### Scenario: Superseded metadata

- **WHEN** reading `adrs/0002-merge-safe-tabletop-overlay-architecture.md` or
  `adrs/0030-fork-divergence-upstream-as-patch-source.md`
- **THEN** the status SHALL read `Superseded`
- **AND** the `Superseded by` field SHALL reference ADR-0031
- **AND** the original rationale text SHALL remain readable as historical
  context

### Requirement: ADR-0003 is rescoped to internal extension discipline

ADR-0003 SHALL be marked `Amended` (with `Amended by: ADR-0031`) stating that
extension-first design remains an internal maintainability rule while
upstream-first preservation and merge parity are retired.

#### Scenario: Amendment content

- **WHEN** reading `adrs/0003-upstream-first-extend-do-not-replace.md`
- **THEN** the status SHALL indicate the amendment
- **AND** the amendment SHALL state that extension-first remains internal,
  upstream-first preservation and merge parity are retired, and ADR-0031
  governs

### Requirement: ADR index and supersession map stay consistent

`adrs/index.md` SHALL list ADR-0031, SHALL update the status entries for
ADR-0002, ADR-0003, and ADR-0030, SHALL add the amended status to the status
legend, and SHALL record ADR-0031 superseding ADR-0002 and ADR-0030.

#### Scenario: Index consistency

- **WHEN** comparing `adrs/index.md` entries against each ADR file's metadata
- **THEN** ADR-0002 and ADR-0030 SHALL show `Superseded`
- **AND** ADR-0003 SHALL show `Amended`
- **AND** the supersession map SHALL list ADR-0031 as superseding ADR-0002 and
  ADR-0030
