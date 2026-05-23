## ADDED Requirements

### Requirement: Emphasized prose phrases SHALL NOT be emitted as NPC actors

The accurate-ingest pipeline SHALL reject narrative/emphasis prose phrases from being classified as NPC actors, monster entries, or scene entities.

The Numillian synthetic fallback path SHALL reuse existing entity-candidate triage semantics when available. It SHALL NOT implement a broad typography-only rule that rejects all lowercase names.

#### Scenario: but this is not true is excluded from module_context NPCs

- **GIVEN** the source markdown contains the text `but this is not true` as an emphasis clause
- **WHEN** the module is generated
- **THEN** `module_context.json` SHALL NOT contain any NPC entry with `name: "but this is not true"`
- **AND** no NPC slug `but_this_is_not_true` SHALL appear.

#### Scenario: but this is not true is excluded from npcs_seed.json

- **GIVEN** the source markdown contains the text `but this is not true`
- **WHEN** the seed writer emits `npcs_seed.json`
- **THEN** the seed NPC list SHALL NOT include an entry with `name: "but this is not true"`
- **AND** SHALL NOT include an entry whose name matches the phrase after normalization.

#### Scenario: but this is not true is excluded from semantic references

- **GIVEN** the module context is built
- **WHEN** semantic authority or reference maps are generated
- **THEN** there SHALL be no `npc:but this is not true` entry in `references`
- **AND** no `npc_scene_authority['but this is not true']` entry.

### Requirement: Legitimate NPCs with short/compound names SHALL remain preserved

The actor filtering heuristic SHALL NOT reject legitimate NPCs whose names happen to be short, lowercase, or contain hyphens.

#### Scenario: Dog-Growl remains

- **GIVEN** source markdown identifies Dog-Growl as a Kenku resident
- **WHEN** the module is generated
- **THEN** Dog-Growl SHALL appear in NPC lists.

#### Scenario: Book-shut remains

- **GIVEN** source markdown identifies Book-shut as a Kenku resident
- **WHEN** the module is generated
- **THEN** Book-shut SHALL appear in NPC lists.

#### Scenario: Deflation remains

- **GIVEN** source markdown identifies Deflation as a Kenku resident
- **WHEN** the module is generated
- **THEN** Deflation SHALL appear in NPC lists.

#### Scenario: Alms-plate remains

- **GIVEN** source markdown identifies Alms-plate as a skull owner/receptacle entry from the First Trial table
- **WHEN** the module is generated
- **THEN** Alms-plate SHALL remain in NPC generation output.

#### Scenario: Lowercase typography alone is not rejection evidence

- **GIVEN** a source-backed NPC candidate has lowercase or hyphenated typography but has source role or location binding evidence
- **WHEN** actor filtering runs
- **THEN** the candidate SHALL NOT be rejected solely because it lacks title-case formatting.

### Requirement: Filtering heuristic SHALL be deterministic and provider-free

The prose-phrase actor filtering heuristic SHALL NOT require LLM classification. It SHALL use the existing deterministic triage helper seam where possible.

#### Scenario: Heuristic runs without LLM calls

- **GIVEN** prose phrase actor filtering is implemented
- **WHEN** the pipeline runs
- **THEN** no LLM provider call SHALL be needed to identify prose phrases
- **AND** the check SHALL complete in sub-millisecond time.

### Requirement: Synthetic fallback SHALL audit filtered candidates

When the synthetic blueprint fallback filters a candidate out of the NPC roster, the blueprint SHALL record the filtered candidate in warnings or equivalent metadata so the exclusion is reviewable.

#### Scenario: Filtered narrative phrase is visible in diagnostics

- **GIVEN** `but this is not true` is rejected as a narrative phrase
- **WHEN** the synthetic blueprint is written
- **THEN** its warnings or metadata SHALL include that the candidate was filtered
- **AND** the candidate SHALL NOT appear in `npc_roster`.
