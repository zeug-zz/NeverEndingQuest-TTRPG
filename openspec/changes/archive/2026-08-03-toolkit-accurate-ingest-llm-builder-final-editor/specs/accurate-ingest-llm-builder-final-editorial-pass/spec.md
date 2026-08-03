## ADDED Requirements

### Requirement: LLM Builder final editor SHALL consume final reconciliation briefs

When `final_reconciliation_required` is reached for editorial-only blockers, the accurate-ingest pipeline SHALL invoke an LLM Builder final editorial pass that consumes `final_reconciliation_brief.json` and returns a strict JSON patch plan.

#### Scenario: Editorial blockers invoke final editor

- **GIVEN** final blocker classification has editorial blockers
- **AND** no fatal blockers are present
- **AND** `final_reconciliation_brief.json` exists
- **WHEN** the packet builder reaches the final reconciliation stage
- **THEN** it SHALL invoke the LLM Builder final editor
- **AND** the editor SHALL receive blocker evidence, source excerpts or source refs when available, generated module summary, editable surfaces, and validation goals.

#### Scenario: Fatal blockers skip final editor

- **GIVEN** final blocker classification has a fatal blocker or mixed fatal/editorial status
- **WHEN** the packet builder reaches final reconciliation handling
- **THEN** it SHALL NOT invoke the LLM Builder final editor
- **AND** it SHALL keep the build blocked with fatal diagnostics.

#### Scenario: Provider failure fails closed

- **GIVEN** final reconciliation is required
- **AND** the configured LLM provider fails, times out, or returns no usable response
- **WHEN** final editor invocation runs
- **THEN** the build SHALL remain blocked
- **AND** diagnostics SHALL identify final reconciliation provider failure.

### Requirement: Final editor SHALL preserve front and middle pipeline artifacts

The final editor SHALL NOT mutate source graph, source manifest, normalized packet, builder blueprint, backstage audit artifacts, or ModuleBuilder input handoff artifacts.

#### Scenario: Source artifacts remain unchanged

- **GIVEN** final reconciliation runs after ModuleBuilder output exists
- **WHEN** the final editor builds prompts, decisions, patches, and reports
- **THEN** upstream source and blueprint artifacts SHALL remain byte-for-byte unchanged
- **AND** final decisions SHALL be recorded only in final reconciliation artifacts and final module outputs.
