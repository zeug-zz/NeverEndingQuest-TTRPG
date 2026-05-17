## ADDED Requirements

### Requirement: Normalization fidelity audit SHALL compare source artifacts to packet output

The toolkit normalization pipeline SHALL produce a source-backed fidelity audit that compares the final normalized packet against source graph, identity, and topology artifacts.

#### Scenario: Required source atom missing from packet

- **GIVEN** a required NPC, location, plot beat, puzzle, clue, or monster source atom exists in source artifacts
- **AND** the normalized packet lacks compatible content for that atom
- **WHEN** fidelity audit runs
- **THEN** `normalization_fidelity_report.json` SHALL include a finding for the missing atom
- **AND** the finding SHALL include source atom ID, severity, category, repairability, and source refs where available.

#### Scenario: Source atom is covered by packet content


- **GIVEN** a source atom exists in source artifacts
- **AND** the normalized packet includes compatible content for that atom
- **WHEN** fidelity audit runs
- **THEN** the atom SHALL be counted as covered
- **AND** the report SHALL include coverage rollups by atom type and criticality.

### Requirement: Fidelity audit SHALL distinguish unsupported packet additions

The fidelity audit SHALL detect packet content that appears unsupported by source artifacts when it replaces, obscures, or competes with source truth.

#### Scenario: Invented replacement location appears in packet

- **GIVEN** source artifacts define keyed source locations
- **AND** the packet uses unrelated invented location names instead
- **WHEN** fidelity audit runs
- **THEN** the report SHALL include unsupported-addition or distortion findings
- **AND** blocking severity SHALL be used when source-critical locations were displaced.

#### Scenario: Extra compatible warning remains non-blocking

- **GIVEN** a packet includes an extra warning or assumption that does not replace source truth
- **WHEN** fidelity audit runs
- **THEN** the audit MAY record an info finding
- **AND** it SHALL NOT block fidelity status solely for that compatible note.

### Requirement: Fidelity audit SHALL degrade safely when source artifacts are unavailable

The fidelity audit SHALL not falsely claim clean fidelity when required source artifacts are missing or unreadable.

#### Scenario: Source graph missing

- **GIVEN** `normalized_packet.json` exists
- **AND** `source_graph.json` is missing or invalid
- **WHEN** fidelity audit runs
- **THEN** the audit status SHALL be `skipped` or `degraded`
- **AND** `normalization_report.json` SHALL record that fidelity could not be verified.

#### Scenario: Packet missing or invalid

- **GIVEN** source artifacts exist
- **AND** `normalized_packet.json` is missing or fails review validation
- **WHEN** fidelity audit runs
- **THEN** the audit status SHALL be `failed`
- **AND** no clean fidelity status SHALL be emitted.
