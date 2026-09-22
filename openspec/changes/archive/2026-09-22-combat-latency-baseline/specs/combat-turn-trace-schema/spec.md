## Purpose

Define the opt-in, read-only schema for per-turn combat latency traces so the
Phase 0 baseline can attribute time and work without changing combat behavior
or duplicating existing context and validation contracts.

## ADDED Requirements

### Requirement: Trace records SHALL expose bounded turn and stage context

Each enabled combat trace record SHALL identify the combat turn, mode when
available, event type, and stage name or site needed to aggregate stage
wall-clock timings. Records SHALL remain bounded and SHALL NOT contain full
prompts, secrets, or unbounded narrative/game-state payloads.

#### Scenario: Stage timing is reportable

- **WHEN** a named combat stage starts and completes while tracing is enabled
- **THEN** the trace SHALL contain a stage event with elapsed wall-clock timing
- **AND** the event SHALL identify the turn or fixture run when available

### Requirement: Provider sites SHALL record latency and token metadata

Provider-call events SHALL record the provider site, elapsed latency in
milliseconds, and available input, output, and total token counts. Missing
provider usage metadata SHALL be represented as absent or null, not fabricated.

#### Scenario: Provider usage is available

- **WHEN** an existing provider call returns usage metadata
- **THEN** the trace SHALL record the site latency and the available token
  counts
- **AND** instrumentation SHALL NOT alter the provider request or response

#### Scenario: Provider usage is unavailable

- **WHEN** an existing provider call has no usable usage metadata
- **THEN** the trace SHALL preserve the site and latency
- **AND** the token fields SHALL remain absent or null

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
the combat path when tracing is disabled and SHALL NOT write game state.

#### Scenario: Existing file activity is observed

- **WHEN** an existing combat stage reads or writes a tracked file while tracing
  is enabled
- **THEN** the trace SHALL record the operation category and site
- **AND** the underlying game-state operation SHALL remain unchanged

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
