# combat-turn-trace-schema Specification

## Purpose
Define the opt-in, read-only schema for per-turn combat latency traces so the
Phase 0 baseline can attribute time and work without changing combat behavior
or duplicating existing context and validation contracts.

## Requirements

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

### Requirement: Compression events SHALL expose cache outcomes

Compression events SHALL identify the compression site, elapsed latency when
available, whether a compression call occurred, and whether the relevant cache
lookup was a hit or miss. This requirement records existing compression
behavior and SHALL NOT change compression policy.

#### Scenario: Compression cache hit is observed

- **WHEN** an existing combat compression path serves a cache hit
- **THEN** the trace SHALL record a cache-hit outcome
- **AND** it SHALL record no new provider call for that cache hit

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

### Requirement: Trace failures SHALL fail open

Any trace configuration, serialization, locking, directory, or output failure
SHALL be swallowed or downgraded to diagnostic output and SHALL NOT block,
alter, or delay combat behavior.

#### Scenario: Trace output is unavailable

- **WHEN** the trace destination cannot be written
- **THEN** combat SHALL continue using its existing behavior
- **AND** no replacement provider call, prompt, or state mutation SHALL occur

### Requirement: Disabled tracing SHALL perform no trace writes

When the trace gate is OFF, the combat path SHALL perform zero trace file
writes and no measurable trace instrumentation work.

#### Scenario: Default gate is disabled

- **WHEN** combat runs with the default trace configuration
- **THEN** no trace file SHALL be created or appended
- **AND** provider calls, prompts, game state, and timings SHALL not be changed

### Requirement: G5 trace records SHALL identify the capture run and work unit

Every G5 trace record SHALL include its distinct `run_id`; provider and file-operation records SHALL also identify the originating `action_id` or `batch_id` when that work unit applies.

#### Scenario: Provider call is attributed to a PC action
- **WHEN** a provider call occurs while processing a captured PC action
- **THEN** its trace record SHALL include the run and action identifiers
- **AND** reports SHALL be able to count that call for the action

#### Scenario: File operation is attributed to an enemy batch
- **WHEN** a tracked file operation occurs while processing the captured enemy batch
- **THEN** its trace record SHALL include the run and batch identifiers
- **AND** reports SHALL be able to count that operation for the batch

#### Scenario: Trace attribution is bounded
- **WHEN** G5 identifiers are emitted
- **THEN** they SHALL identify runs and work units without embedding full prompts, user messages, secrets, or unbounded game state

### Requirement: G5 capture steps SHALL preserve both timing measurements

Each G5 PC action and enemy-batch completion record SHALL report separate non-negative work-only and quiet-window elapsed durations; neither duration SHALL be substituted for the other.

#### Scenario: Driver quiet window inflates step elapsed time
- **WHEN** a captured step includes a driver quiet-window wait
- **THEN** the evidence SHALL preserve both work-only and quiet-window elapsed durations
- **AND** the report SHALL use work-only timing for the corresponding latency target while displaying both measurements

#### Scenario: No quiet-window inflation occurs
- **WHEN** the measured step completes without a quiet-window wait
- **THEN** both timing fields SHALL still be reported from their own measurement boundaries
- **AND** neither missing value SHALL be fabricated as zero

### Requirement: Tactical trace correlation SHALL remain bounded

Tactical events SHALL correlate by bounded enemy `batch_id` and MAY include bounded plan/receipt IDs, standing-order origin/outcome, distinct background-site attribution, actor/feature IDs, cover outcomes, and self-preservation outcomes. Traces SHALL exclude prompts, secrets, absolute paths, and unbounded narrative or game-state data.

#### Scenario: Synchronous commander plan is traced

- **WHEN** a synchronous commander plan is submitted and validated
- **THEN** plan and resulting decision events SHALL share the enemy batch correlation
- **AND** the trace SHALL identify the plan outcome and bounded default reasons

#### Scenario: Standing-order requests are attributed to their batch

- **WHEN** an initial standing-order request or re-plan is submitted, consumed, failed, cancelled, or invalidated
- **THEN** its bounded status, distinct background request attribution, and receipt correlation SHALL be associated with the identified enemy batch
- **AND** a late response SHALL NOT be attributed to or consumed by a later batch

#### Scenario: Cover state is traced

- **WHEN** authored cover applies to or expires for a combatant
- **THEN** the trace MAY record bounded actor, feature, cover-type, and state identifiers
- **AND** it SHALL NOT serialize the full encounter or location data

#### Scenario: Flight and surrender are traced
- **WHEN** a creature flees or surrenders during a correlated enemy batch
- **THEN** the trace SHALL associate its bounded actor ID and `fled` or `surrendered` outcome with that batch
- **AND** it SHALL NOT contain full encounter state or narrative text
