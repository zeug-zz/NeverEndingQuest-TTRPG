# Spec Delta

## ADDED Requirements

### Requirement: The report SHALL summarize G5T commander observations

The report SHALL summarize G5T P1/P4 latency, synchronous calls by plan/narration/validation site, background standing-order calls by distinct site, per-batch writes, plan legality, and behavioral evidence. Optional standing-order counts and outcomes SHALL be separate. Existing G1/G3/G4/G5/G5R outputs SHALL remain unchanged.

#### Scenario: Three G5T runs are summarized

- **WHEN** the input contains three valid G5T captures for each party shape
- **THEN** the report SHALL show all three raw latency observations and the median for each shape
- **AND** it SHALL show raw call and write counts for each observed batch
- **AND** it SHALL summarize plan choice legality only from validation records

#### Scenario: G5T target is evaluated

- **WHEN** complete G5T records are present
- **THEN** the report SHALL identify primary-acceptance batches exceeding two synchronous provider calls, any synchronous validation call, raw writes above one history write plus one encounter write plus one write per distinct character whose canonical state changed, or a party-shape median exceeding 15000 ms
- **AND** it SHALL report background standing-order counts separately, with no more than two such requests per batch
- **AND** it SHALL expose the observations supporting each comparison
- **AND** a missing measurement SHALL be diagnosed rather than treated as zero

#### Scenario: Optional standing-order results are present

- **WHEN** G5T input includes background standing-order records
- **THEN** the report SHALL separate initial/re-plan counts and completed, failed, cancelled, expired, unavailable, and not-requested outcomes from primary synchronous results
- **AND** optional standing-order evidence SHALL NOT waive or replace primary G5T targets

### Requirement: G5T report SHALL expose self-preservation evidence

For G5T captures, the provider-free report SHALL distinguish observed `fled` and `surrendered` outcomes using bounded traces and authoritative encounter snapshots. It SHALL report whether the flee used Disengage without an attack, whether the creature was removed from later actor/target menus, and whether the existing exit/XP path completed when all enemies were defeated.

#### Scenario: Flight and surrender observations are present
- **WHEN** G5T records contain per-creature self-preservation outcomes
- **THEN** the report SHALL show the outcome and matching `defeatReason` for each observed creature
- **AND** it SHALL expose the evidence for actor/target removal and existing lifecycle completion

#### Scenario: Required self-preservation evidence is missing
- **WHEN** a required capture lacks an authoritative flee or surrender observation
- **THEN** the report SHALL diagnose the missing evidence
- **AND** it SHALL NOT claim the corresponding G5T behavior assertion passed
