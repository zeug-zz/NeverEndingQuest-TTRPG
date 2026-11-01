# Spec Delta

## MODIFIED Requirements

### Requirement: Trace records SHALL expose bounded turn and stage context

Each enabled combat trace record SHALL identify the combat turn, mode when
available, event type, and stage name or site needed to aggregate stage
wall-clock timings. Records causally attributable to an enemy batch SHALL also
carry a bounded run-local `batch_id`; batch correlation SHALL NOT contain
prompt text, secrets, absolute paths, or unbounded narrative/game-state
payloads.

#### Scenario: Stage timing is reportable

- **WHEN** a named combat stage starts and completes while tracing is enabled
- **THEN** the trace SHALL contain a stage event with elapsed wall-clock timing
- **AND** the event SHALL identify the turn or fixture run when available

#### Scenario: Enemy batch events are correlated

- **WHEN** provider, decision, persistence, or stage events occur as part of an
  enemy batch
- **THEN** each such event SHALL carry the same bounded `batch_id`
- **AND** the report SHALL be able to isolate that batch without parsing prose

### Requirement: Provider sites SHALL record latency and token metadata

Provider-call events SHALL record the provider site, elapsed latency in
milliseconds, and available input, output, and total token counts. Missing
provider usage metadata SHALL be represented as absent or null, not fabricated.
An additional provider request caused by a combat-validator rejection retry
SHALL include a bounded retry-reason code and attempt identity sufficient to
correlate only that retry's provider requests for outcome-normalized comparison.

#### Scenario: Provider usage is available

- **WHEN** an existing provider call returns usage metadata
- **THEN** the trace SHALL record the site latency and the available token
  counts
- **AND** instrumentation SHALL NOT alter the provider request or response

#### Scenario: Provider usage is unavailable

- **WHEN** an existing provider call has no usable usage metadata
- **THEN** the trace SHALL preserve the site and latency
- **AND** the token fields SHALL remain absent or null

#### Scenario: Validator rejection retry is attributable

- **WHEN** a provider request occurs on an attempt after a combat-validator
  rejection
- **THEN** its event SHALL identify the retry attempt and use the bounded
  `validator_rejection` retry reason
- **AND** unrelated transport retries SHALL NOT be labeled as validator retries

### Requirement: File operations SHALL be counted without mutating state

Trace records SHALL count observed combat file reads and writes by bounded
operation category or site. Instrumentation SHALL NOT add a file operation to
the combat path when tracing is disabled and SHALL NOT write game state. For
G5R, each physical atomic gameplay/history file write attributable to an enemy
batch SHALL emit one write event with its `batch_id`, bounded target kind, and
opaque run-local target identity; a helper that writes multiple files SHALL
emit one event per physical write and SHALL NOT count as one grouped write.
Trace and evidence output writes SHALL be excluded from the gameplay/history
write count.

#### Scenario: Existing file activity is observed

- **WHEN** an existing combat stage reads or writes a tracked file while tracing
  is enabled
- **THEN** the trace SHALL record the operation category and site
- **AND** the underlying game-state operation SHALL remain unchanged

#### Scenario: Grouped helper writes multiple batch files

- **WHEN** one persistence helper atomically writes multiple gameplay/history
  files for an enemy batch
- **THEN** the trace SHALL emit one write event for each physical file write
- **AND** every event SHALL carry the batch correlation and a bounded target
  identity without exposing an absolute path

#### Scenario: Trace output is not a gameplay-state write

- **WHEN** an enemy batch emits combat trace or capture-evidence files
- **THEN** those output writes SHALL NOT contribute to the G5R gameplay/history
  file-write count
