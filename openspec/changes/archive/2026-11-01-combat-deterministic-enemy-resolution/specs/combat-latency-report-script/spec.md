# Spec Delta

## MODIFIED Requirements

### Requirement: The report SHALL summarize baseline latency and work

For valid trace records, the report SHALL provide stage wall-clock timings,
provider-call counts and latency by site, available token totals, compression
call counts and cache hit rate, file read/write counts, and NL fast-path
hit/miss outcomes. For G5R input it SHALL additionally report, by party shape,
the three run-level enemy-batch work-only latencies and their median, raw
provider calls, raw gameplay/history writes per batch, resolver eligibility,
and the normalized provider-call and write comparisons. Raw observations SHALL
remain visible beside every normalized value.

#### Scenario: Complete trace is reported

- **WHEN** the input contains the required event classes
- **THEN** the output SHALL include the corresponding aggregate sections
- **AND** aggregate values SHALL be derived only from observed records

#### Scenario: Three G5R runs are summarized

- **WHEN** the input contains three complete, identity-matched run bundles for
  a party shape
- **THEN** the report SHALL show every run-level batch work-only latency and
  the median of those three values
- **AND** it SHALL show raw and outcome-normalized regression metrics as
  separate values

#### Scenario: Supported batch call count is normalized

- **WHEN** the trace identifies a batch as `resolver_supported`
- **THEN** the report SHALL derive its normalized resolver call count only from
  correlated narration-only provider events
- **AND** it SHALL report a missing narration event or any validation event as
  a deviation rather than silently counting one call

#### Scenario: Physical batch writes are reported

- **WHEN** the trace contains correlated gameplay/history write events for a
  batch
- **THEN** the raw batch write count SHALL count each physical write event
- **AND** grouped persistence helpers SHALL NOT collapse multiple writes into
  one reported write

#### Scenario: Outcome attribution is computed from local bundle evidence

- **WHEN** the report computes normalized provider-call and damaged-PC write deltas
- **THEN** changed-PC targets SHALL be derived from per-PC HP differences between the enemy-batch `step-NNN-before` and `step-NNN-after` snapshots
- **AND** validator-rejection retry requests SHALL be derived from receipts/trace as `combat_main` attempts following a failed `combat_validation` in the same batch
- **AND** the report SHALL remain provider-free

### Requirement: The report SHALL handle malformed or incomplete input explicitly

The script SHALL reject or boundedly diagnose malformed JSONL records, missing
required fields, unreadable files, and empty input. It SHALL NOT silently treat
missing measurements as zero when that would misrepresent the baseline. For
G5R it SHALL require exactly three complete run bundles per party shape and
complete retry-attribution and damaged-PC outcome evidence for each normalized
comparison; missing data SHALL be BLOCKED, not zero-filled.

#### Scenario: One malformed line is present

- **WHEN** a trace file contains valid records and a malformed JSONL line
- **THEN** the report SHALL identify the malformed input and its line context
- **AND** it SHALL either produce a clearly degraded report or exit non-zero
  according to the documented CLI contract

#### Scenario: G5R run bundle or outcome evidence is incomplete

- **WHEN** fewer than three complete run bundles exist or normalized outcome
  evidence is missing
- **THEN** the report SHALL mark the affected party-shape comparison BLOCKED
- **AND** it SHALL preserve available raw values without substituting zero
- **AND** missing attribution SHALL stop the builder from asserting a normalized comparison
