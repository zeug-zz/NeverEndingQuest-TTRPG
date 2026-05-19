## ADDED Requirements

### Requirement: Numillian publication SHALL depend on final source fidelity

Production Numillian publishability SHALL compose readiness, semantic publishability, and final source-fidelity status.

#### Scenario: Blocked source fidelity blocks publication

- **GIVEN** production Numillian has `source_fidelity_status="blocked"`
- **WHEN** publishability is audited
- **THEN** final `publishable_status` SHALL NOT be `pass`
- **AND** the source-fidelity blocker SHALL be visible in the audit output.

#### Scenario: Passing source fidelity allows other gates to decide

- **GIVEN** production Numillian has `source_fidelity_status="pass"`
- **WHEN** readiness and semantic publication gates pass
- **THEN** publishability MAY pass.

#### Scenario: Degraded source fidelity requires waiver

- **GIVEN** production Numillian has `source_fidelity_status="degraded"`
- **WHEN** publishability is audited
- **THEN** publication SHALL require a valid source-fidelity waiver before pass status is allowed.

### Requirement: Numillian reports SHALL agree on source-fidelity outcome

Final module reports SHALL expose a consistent source-fidelity status.

#### Scenario: Reports agree after proof run

- **GIVEN** production Numillian has been built or refreshed
- **WHEN** `source_fidelity_report.json`, `accurate_ingest_benchmark_report.json`, `toolkit_build_report.json`, and `audit_module_publishability.py` are inspected
- **THEN** they SHALL agree on the final source-fidelity status or clearly identify benchmark-specific degraded details.

#### Scenario: Benchmark fixture expectations are decisive evidence

- **GIVEN** the Numillian benchmark fixture has required NPC/location/puzzle/lore/tone expectations
- **WHEN** the benchmark runner reports a blocked status
- **THEN** final publication SHALL be blocked unless an explicit accepted waiver contract permits degraded publication.
