# toolkit-blueprint-llm-enrichment-passes Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-llm-blueprint-enrichment. Update Purpose after archive.
## Requirements
### Requirement: Blueprint enrichment SHALL run bounded pass-oriented LLM enrichment

The blueprint enrichment pipeline SHALL enrich source-blueprint facts through bounded pass-specific prompts rather than a single full-source prompt.

#### Scenario: NPC pass uses bounded source excerpts

- **GIVEN** blueprint enrichment is enabled
- **AND** source graph or identity artifacts provide NPC candidate source refs
- **WHEN** the NPC enrichment pass runs
- **THEN** the provider request SHALL include only bounded source excerpts relevant to the NPC pass
- **AND** it SHALL NOT send the entire uploaded source as one monolithic prompt.

#### Scenario: NPC pass is implemented before later passes

- **GIVEN** this change is being implemented incrementally
- **WHEN** the first runtime enrichment pass is added
- **THEN** the first pass SHALL target NPC enrichment
- **AND** location, plot, puzzle, encounter, item, and tone passes MAY remain skipped or not implemented until later tasks.

#### Scenario: Later passes preserve pass boundaries

- **GIVEN** location, plot, puzzle, encounter, item, or tone enrichment passes are implemented
- **WHEN** each pass runs
- **THEN** each pass SHALL use pass-specific excerpts and targets
- **AND** pass diagnostics SHALL identify which pass produced each applied patch, warning, or error.

### Requirement: NPC enrichment SHALL respect candidate triage decisions

NPC enrichment SHALL consume candidate triage results when present and SHALL NOT promote rejected narrative phrases into actor records.

#### Scenario: Narrative phrase remains rejected

- **GIVEN** candidate triage classifies `but this is not true` as rejected or non-actor text
- **WHEN** NPC enrichment runs
- **THEN** the phrase SHALL NOT appear in NPC roster patches, module context NPCs, media queues, or source-fidelity expected NPC outputs.

#### Scenario: Underbound valid NPC can be enriched

- **GIVEN** Dog-Growl, Book-shut, and Deflation are kept NPC candidates from The Rookery source excerpt
- **WHEN** NPC enrichment proposes updates for those candidates
- **THEN** accepted patches MAY add role/context/location-binding prose or source refs
- **AND** those patches SHALL preserve the original source names and canonical identities.

