## ADDED Requirements

### Requirement: Readable Homebrew uploads SHALL produce source graph artifacts before normalization

Readable Homebrew upload sources routed through normalization-required workflow SHALL produce deterministic source manifest and source graph artifacts before the existing LLM normalization call is made.

#### Scenario: Workspace receives source graph artifacts

- **GIVEN** a readable markdown upload is routed to normalization-required workflow
- **AND** an artifact workspace is available
- **WHEN** normalization begins
- **THEN** the pipeline SHALL write `source_manifest.json`
- **AND** it SHALL write `source_graph.json`
- **AND** it SHALL continue to produce existing normalization artifacts.

#### Scenario: Source graph generation degrades safely

- **GIVEN** source graph generation raises an unexpected exception
- **WHEN** the existing source remains readable
- **THEN** the pipeline SHALL record degraded source graph status in the normalization report
- **AND** it SHALL continue the current LLM normalization behavior
- **AND** it SHALL NOT silently mark source graph generation as successful.

### Requirement: Source graph atoms SHALL be evidence-backed

Each source graph atom SHALL include enough evidence for later review, fidelity verification, and repair prompts.

#### Scenario: Captured NPC includes evidence

- **GIVEN** the source contains a named NPC in a table, bold span, or location entry
- **WHEN** source graph generation captures that NPC
- **THEN** the NPC atom SHALL include a stable `id`
- **AND** it SHALL include `type="npc"`
- **AND** it SHALL include `criticality`
- **AND** it SHALL include `confidence`
- **AND** it SHALL include at least one `source_refs` entry with section context and excerpt.

#### Scenario: Captured location includes evidence

- **GIVEN** the source contains a numbered map-key heading such as `### 1. Brooksteps Inn`
- **WHEN** source graph generation captures that location
- **THEN** the location atom SHALL preserve the original display name
- **AND** it SHALL include `type="location"`
- **AND** it SHALL include line or section evidence.

### Requirement: Map-key and room-style locations SHALL be mechanically detected

The source graph foundation SHALL detect common adventure location heading styles without requiring an LLM.

#### Scenario: Numillian-style map key is detected

- **GIVEN** markdown contains numbered map-key headings under a locations or map-key section
- **WHEN** source graph generation runs
- **THEN** each numbered location heading SHALL produce a location candidate or atom
- **AND** the original source name SHALL be preserved.

#### Scenario: Existing room format remains supported

- **GIVEN** markdown contains existing `## Room N: Title` style headings
- **WHEN** source graph generation runs
- **THEN** each room heading SHALL produce a location candidate or atom
- **AND** behavior SHALL remain compatible with deterministic importer expectations.

### Requirement: Source graph foundation SHALL classify criticality conservatively

Source graph atoms SHALL classify source candidates so later fidelity phases can distinguish required adventure structure from likely false positives.

#### Scenario: Map-key locations are required

- **GIVEN** a source atom comes from a numbered map-key location heading
- **WHEN** criticality is assigned
- **THEN** the atom SHALL default to `required` unless there is explicit evidence that it is optional, lore-only, or ignorable.

#### Scenario: Proper-noun-only candidates are not over-promoted

- **GIVEN** a candidate is detected only by broad proper noun matching
- **AND** it has no table, bold-span, heading, location-entry, or quest evidence
- **WHEN** criticality is assigned
- **THEN** the atom SHALL NOT default to `required`.

### Requirement: Existing normalization packet compatibility SHALL be preserved

Adding source graph artifacts SHALL NOT invalidate existing normalized packet review behavior.

#### Scenario: Legacy packet still validates

- **GIVEN** a normalized packet has the existing required identity fields
- **AND** it lacks source graph references
- **WHEN** `validate_review_packet(...)` runs
- **THEN** the packet SHALL remain valid if it satisfied the previous contract.
