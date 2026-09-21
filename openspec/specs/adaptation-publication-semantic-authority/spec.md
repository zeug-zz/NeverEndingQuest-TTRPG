# adaptation-publication-semantic-authority Specification

## Purpose
Builds the deterministic semantic authority required to turn authored names and player-facing travel phrases into a playable, publishable adaptation contract and supplies bounded evidence to the finalization loop.

## Requirements

### Requirement: Semantic authority is generated from authored evidence

The adaptation pipeline MUST build and persist a module-local `semantic_authority` payload from authored context, areas, plot, source manifests, and normalized packet evidence before readiness or publication checks.

#### Scenario: Authority payload is complete

- **WHEN** authored locations, aliases, destination phrases, and scene entities can be extracted
- **THEN** the pipeline MUST persist canonical mappings with provenance
- **AND** downstream readiness and publication checks MUST consume the current payload

#### Scenario: Authority evidence is incomplete

- **WHEN** a required authority category cannot be built from available authored evidence
- **THEN** the pipeline MUST persist a bounded diagnostic identifying the missing category
- **AND** the module MUST remain non-publishable until the category is repaired

### Requirement: Unique destination phrases resolve automatically

The semantic authority layer MUST resolve a player-facing destination phrase to a canonical location when exactly one supported alias or source-backed mapping matches.

#### Scenario: Source-backed phrase has one canonical location

- **WHEN** `moonlit-shrine` or an equivalent phrase uniquely matches one authored location
- **THEN** the pipeline MUST add a deterministic alias with source provenance
- **AND** travel readiness and gameplay probes MUST use the canonical location ID

#### Scenario: Destination phrase remains unresolved

- **WHEN** no canonical location matches a player-facing destination phrase
- **THEN** the pipeline MUST emit a concrete unresolved-destination blocker
- **AND** it MUST not invent a location or silently drop the phrase

### Requirement: Adaptation Fidelity Is Informational When Playability Passes

For intentional `llm_adaptation` builds, source-fidelity differences MUST remain visible in provenance and diagnostic reports but MUST NOT independently block publication when structural, mechanical, semantic, gameplay, and publication gates pass.

#### Scenario: Adapted content is intentionally reinterpreted

- **WHEN** the adapted module does not preserve literal source structure but has complete current semantic authority and passes all playable publication gates
- **THEN** the pipeline MUST report source fidelity as informational adaptation provenance
- **AND** the module MAY be marked playable and publishable

#### Scenario: Structural or semantic authority is missing

- **WHEN** required canonical authority, aliases, or scene-entity evidence is missing
- **THEN** the module MUST remain non-publishable regardless of source-fidelity treatment

### Requirement: Alias evidence MUST not manufacture unresolved destination blockers

The semantic authority builder MUST treat authored aliases as exact canonical authority seeds. It MUST NOT promote token windows synthesized solely from an alias string into independent player-facing destination phrases unless those phrases are separately observed in player-facing authored evidence.

#### Scenario: Alias has a trailing terminal word

- **WHEN** a location has the authored alias `The Empty Village Road Square`
- **THEN** the exact alias MUST resolve to that location with alias provenance
- **AND** derived windows such as `empty village road` or `village road` MUST NOT become unresolved blockers solely because they were extracted from the alias source

#### Scenario: Similar phrase is independently player-facing

- **WHEN** `village road` is separately used in player-facing authored prose and no canonical authority resolves it
- **THEN** the phrase MUST remain an unresolved destination blocker
- **AND** the builder MUST retain the prose source reference for remediation

### Requirement: Duplicate raw location IDs MUST remain area-scoped internally

The semantic authority layer MUST distinguish location records by an area-scoped internal identity when the same raw `location_id` occurs in multiple areas. It MUST preserve the raw `location_id` as a compatibility field, but MUST NOT use a global last-write-wins lookup for location names, aliases, destination resolutions, shortform anchors, or scene authority.

#### Scenario: Same raw ID in two areas

- **WHEN** `EVR001` and `FC001` each contain a location with raw ID `K01` but different names and aliases
- **THEN** each exact name and alias MUST resolve to the correct area-scoped location record
- **AND** the semantic-authority payload MUST retain the area provenance and correct location name for each resolution

#### Scenario: Raw ID has no area context

- **WHEN** a destination phrase resolves only to a raw ID shared by multiple areas and no area context disambiguates it
- **THEN** the phrase MUST remain ambiguous
- **AND** the builder MUST NOT silently select the last indexed area
