## MODIFIED Requirements

### Requirement: Builder blueprint SHALL be generated from source-backed Phase 2-3 artifacts

The accurate-ingest builder handoff pipeline SHALL generate `builder_blueprint.json` from source graph, identity, topology, normalized packet, fidelity, and candidate triage artifacts rather than from freeform model prose alone.

#### Scenario: Blueprint uses source artifacts

- **GIVEN** source graph, identity report, plot topology report, normalized packet, fidelity report, and any available candidate triage report artifacts exist
- **AND** final fidelity status allows builder handoff
- **WHEN** blueprint generation runs
- **THEN** `builder_blueprint.json` SHALL include source-backed module identity, area plan, location roster, NPC roster, plot graph, puzzle graph, clue graph, encounter plan, item roster, tone requirements, source locks, source refs, and warnings
- **AND** source atom IDs and original display names SHALL be preserved where available
- **AND** rejected or non-actor triage candidates SHALL NOT be promoted into actor rosters.

#### Scenario: Required source location appears in blueprint roster

- **GIVEN** a required keyed source location exists in `source_graph.json`
- **WHEN** blueprint generation succeeds
- **THEN** the location SHALL appear in `location_roster` by original source name or approved mapped equivalent
- **AND** the entry SHALL include source evidence or source atom ID.

#### Scenario: Required source NPC appears in blueprint roster

- **GIVEN** a required source NPC exists in source graph, identity artifacts, or candidate triage artifacts
- **AND** the candidate is not rejected or reclassified as a non-actor
- **WHEN** blueprint generation succeeds
- **THEN** the NPC SHALL appear in `npc_roster`
- **AND** aliases, source bindings, and original display names SHALL be preserved where available.

## ADDED Requirements

### Requirement: Blueprint generation SHALL honor candidate triage decisions

Blueprint generation SHALL filter, preserve, or warn about entity candidates according to triage decisions before writing actor/entity rosters.

#### Scenario: Rejected candidate excluded from NPC roster

- **GIVEN** candidate triage marks a candidate as `reject`
- **WHEN** blueprint generation builds `npc_roster`
- **THEN** the candidate SHALL NOT appear in `npc_roster`
- **AND** the blueprint report SHALL retain enough warning or report linkage for operator review.

#### Scenario: Kept NPC retains source binding

- **GIVEN** candidate triage marks Dog-Growl as `keep` with adjudicated type `true_npc`
- **AND** the triage decision includes The Rookery as a source-backed location binding
- **WHEN** blueprint generation writes the NPC roster
- **THEN** the Dog-Growl entry SHALL preserve the display name
- **AND** the entry SHALL include source refs or source binding metadata connecting it to The Rookery.

#### Scenario: Missing triage remains compatible

- **GIVEN** a legacy accurate-ingest workspace lacks candidate triage artifacts
- **WHEN** blueprint generation runs
- **THEN** generation SHALL continue using existing source graph and identity artifacts
- **AND** `builder_blueprint_report.json` SHALL warn that candidate triage was not available.
