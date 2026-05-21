## ADDED Requirements

### Requirement: Accurate-ingest entity candidates SHALL be adjudicated before becoming canonical entities

Deterministic source extraction may emit broad entity candidates, but accurate-ingest builder handoff SHALL require a triage decision before a candidate is treated as a canonical NPC, monster actor, item, faction, location, clue, plot note, or tone marker.

#### Scenario: Candidate receives persisted triage decision

- **GIVEN** source extraction emits an entity candidate with candidate text, candidate slug, proposed type, and source evidence
- **WHEN** entity candidate triage runs
- **THEN** the triage output SHALL include candidate text, candidate slug or id, proposed type, adjudicated type, decision, reason, and source reference when available
- **AND** the decision SHALL be one of `keep`, `reject`, or `reclassify`.

#### Scenario: Triage report is reviewable

- **GIVEN** candidate triage produces one or more decisions
- **WHEN** accurate-ingest workspace artifacts are persisted
- **THEN** the decisions SHALL be written to `entity_candidate_triage_report.json` or an equivalent stable triage section in `identity_resolution_report.json`
- **AND** downstream blueprint generation SHALL be able to read the decision data deterministically.

### Requirement: Narrative phrases SHALL NOT become actor records

Candidates adjudicated as narrative phrases, plot notes, tone markers, or rejected prose fragments SHALL NOT be promoted into NPC, monster, or scene-actor rosters.

#### Scenario: Numillian fabricated-mindscape assertion is rejected

- **GIVEN** a deterministic candidate has slug `but_this_is_not_true`
- **AND** source evidence shows it is a prose assertion about Shuluth's fabricated mindscape
- **WHEN** entity candidate triage runs
- **THEN** the decision SHALL be `reject` or `reclassify`
- **AND** the adjudicated type SHALL NOT be `true_npc`, `scene_actor`, or `monster_actor`
- **AND** the candidate SHALL NOT appear in blueprint NPC roster output.

#### Scenario: Reclassified narrative text remains usable as non-actor context

- **GIVEN** a narrative phrase contains source-relevant plot, clue, or tone information
- **WHEN** triage reclassifies it as `plot_note`, `tone_marker`, or equivalent non-actor type
- **THEN** the source text MAY be preserved in non-actor blueprint context
- **AND** it SHALL NOT appear in actor rosters or media queues.

### Requirement: Kept NPC candidates SHALL carry source-backed bindings

Candidates adjudicated as `true_npc` SHALL include at least one useful source-backed binding before blueprint handoff: location binding, plot binding, faction binding, or explicit source role.

#### Scenario: Rookery Kenku are kept with location binding

- **GIVEN** source text states that The Rookery is inhabited by Dog-Growl, Book-shut, and Deflation
- **WHEN** entity candidate triage processes those candidates
- **THEN** each candidate SHALL be kept or reclassified as a source NPC equivalent
- **AND** each candidate SHALL include a binding to The Rookery or its canonical location id
- **AND** each candidate SHALL preserve enough source role/context for ModuleBuilder handoff.

#### Scenario: Underbound NPC is warning or blocker by criticality

- **GIVEN** a candidate is adjudicated as `true_npc`
- **AND** it lacks location, plot, faction, and explicit source-role binding
- **WHEN** the triage report is produced
- **THEN** the report SHALL include a warning or blocker according to candidate criticality
- **AND** the candidate SHALL NOT silently enter the blueprint as fully source-ready.

### Requirement: Candidate triage SHALL degrade safely

When provider-backed adjudication, cache lookup, or triage persistence fails, accurate ingest SHALL preserve existing source artifacts and report degraded status without corrupting builder blueprint artifacts.

#### Scenario: Provider adjudication fails

- **GIVEN** a provider-backed triage seam is enabled
- **AND** the provider call fails, times out, or returns invalid JSON
- **WHEN** triage handles the failure
- **THEN** source graph and identity artifacts SHALL remain unchanged
- **AND** the triage report SHALL include degraded status and failure reason
- **AND** obvious deterministic narrative phrase rejections SHALL still be applied when available.

#### Scenario: No triage artifact exists for legacy workspace

- **GIVEN** a workspace was produced before entity candidate triage existed
- **WHEN** builder blueprint generation runs
- **THEN** the build SHALL not crash solely because the triage report is missing
- **AND** the blueprint report SHALL include a warning that triage was unavailable.
