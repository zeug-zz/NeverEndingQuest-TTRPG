## ADDED Requirements

### Requirement: Module NPC recruitment SHALL preserve module canonical identity
When a recruited NPC resolves to a module-authored NPC, the party NPC entry SHALL preserve the module canonical display name.

#### Scenario: Module NPC name survives stale character-file overlap
- **GIVEN** the current module defines an NPC named `Thorn-Touched Dryad Sylara`
- **AND** a pre-existing character file named `dryad_sylara.json` has display name `Dryad Sylara`
- **WHEN** `updatePartyNPCs` adds `Thorn-Touched Dryad Sylara`
- **THEN** the party NPC entry SHALL use `Thorn-Touched Dryad Sylara` as its `name`
- **AND** the party NPC entry SHALL NOT be renamed to `Dryad Sylara` by fuzzy character-file matching

### Requirement: Character-file reuse SHALL be linkage, not identity authority, for module recruits
Existing character files MAY be linked to recruited module NPCs for continuity, stats, or media, but SHALL NOT override module-authored identity unless the character file is an exact canonical match or has matching source metadata.

#### Scenario: Fuzzy file match is linked without renaming
- **GIVEN** a module recruit named `Thorn-Touched Dryad Sylara`
- **AND** the best fuzzy file candidate is `dryad_sylara.json`
- **WHEN** recruitment safely reuses that file as continuity metadata
- **THEN** the party NPC entry MAY include `character_file_ref: "dryad_sylara"`
- **AND** the party NPC `name` SHALL remain `Thorn-Touched Dryad Sylara`

#### Scenario: Exact character-file recruit still works
- **GIVEN** a recruited NPC name exactly matches an existing character file identity
- **WHEN** the NPC is added to the party
- **THEN** existing exact-name character-file reuse MAY continue
- **AND** no source metadata is required when no module identity is involved

### Requirement: Party NPC entries SHALL carry source identity metadata for module recruits
When module NPC identity is known, party NPC entries SHALL include source metadata sufficient for future dedupe, media, and lifecycle decisions.

#### Scenario: Module recruit stores source identity
- **GIVEN** a party NPC is recruited from the current module and current location
- **WHEN** the party tracker is updated
- **THEN** the party NPC entry SHALL include `source_module`, `source_npc_name`, `source_entity_slug`, and `recruited_from_location_id` when those values are known

#### Scenario: Legacy party NPC remains valid
- **GIVEN** an existing party NPC entry with only `name` and `role`
- **WHEN** party tracker data is loaded or emitted to the UI
- **THEN** the entry SHALL remain valid
- **AND** the UI SHALL continue to render it using existing fallback behavior

### Requirement: Location NPC strip dedupe SHALL use source identity when available
The party data socket payload SHALL suppress current-location NPC duplicates when a party NPC source identity matches the current-location NPC identity.

#### Scenario: Recruited module NPC does not render twice
- **GIVEN** `partyNPCs` contains `Thorn-Touched Dryad Sylara` with source identity metadata
- **AND** the current location still lists `Thorn-Touched Dryad Sylara` in its NPC array
- **WHEN** the party data socket payload is built
- **THEN** `members` SHALL include the party NPC
- **AND** `location_npcs` SHALL NOT include a duplicate current-location copy of the same source NPC

#### Scenario: Distinct similar NPCs remain distinct
- **GIVEN** a party NPC and a location NPC have similar display tokens but different source identities
- **WHEN** the party data socket payload is built
- **THEN** the location NPC SHALL NOT be suppressed solely by broad fuzzy similarity

### Requirement: Recruitment hardening SHALL avoid cross-session identity crosstalk
Prior-session character files SHALL NOT become authoritative over current-module NPC identity through broad fuzzy matching.

#### Scenario: Prior companion file cannot rename current module NPC
- **GIVEN** a character file from prior gameplay partially matches a current module NPC name
- **WHEN** the current module NPC is recruited
- **THEN** the prior file SHALL NOT replace the current module NPC's canonical display name
- **AND** any reuse of that file SHALL be explicit metadata rather than implicit identity replacement
