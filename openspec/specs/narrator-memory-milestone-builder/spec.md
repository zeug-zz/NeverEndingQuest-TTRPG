# narrator-memory-milestone-builder Specification

## Purpose
TBD - created by archiving change narrator-memory-milestone-injection. Update Purpose after archive.
## Requirements
### Requirement: Milestone builder function exists
The system SHALL provide `build_campaign_milestones(entity_ids: List[str], max_events: int = 15) -> str` in `core/memory/memory_retrieval.py` that constructs a campaign milestone timeline block from memory DB events.

#### Scenario: Function signature and location
- **WHEN** `build_campaign_milestones` is imported from `core.memory.memory_retrieval`
- **THEN** the function accepts a list of entity ID strings and an optional `max_events` integer parameter (default 15)
- **AND** returns a string containing formatted milestone entries

### Requirement: Milestone filtering by retrieval score
The milestone builder SHALL filter events to include only those with `retrieval_score >= 30` OR `pinned == 1`.

#### Scenario: High-score events included
- **WHEN** an event has `retrieval_score = 45` and `pinned = 0`
- **THEN** the event SHALL be included in milestone output

#### Scenario: Pinned events included regardless of score
- **WHEN** an event has `retrieval_score = 10` and `pinned = 1`
- **THEN** the event SHALL be included in milestone output

#### Scenario: Low-score unpinned events excluded
- **WHEN** an event has `retrieval_score = 20` and `pinned = 0`
- **THEN** the event SHALL NOT be included in milestone output

### Requirement: Milestone deduplication across entities
The milestone builder SHALL deduplicate events when the same event is linked to multiple entities in the input list.

#### Scenario: Shared event appears once
- **WHEN** event E1 is linked to both entity "vitreol" and entity "acheron"
- **AND** both entity IDs are passed to `build_campaign_milestones`
- **THEN** event E1 SHALL appear exactly once in the output

### Requirement: Milestone event limit
The milestone builder SHALL return at most `max_events` entries, sorted by `retrieval_score` descending.

#### Scenario: More qualifying events than limit
- **WHEN** 25 events qualify (score >= 30 or pinned)
- **AND** `max_events = 15`
- **THEN** the output SHALL contain exactly 15 events
- **AND** the 15 events SHALL be the highest-scoring events

### Requirement: Milestone entry format
Each milestone entry SHALL be formatted as `[YYYY-MM-DD] entity_id: summary` with summary truncated to `MAX_MILESTONE_CHARS` (120 characters).

#### Scenario: Entry formatting
- **WHEN** an event has `event_ts = "2026-03-14T10:30:00"`, `entity_id = "vitreol"`, and `summary = "Died to stirge bite in Thornwood cave"`
- **THEN** the formatted entry SHALL be `[2026-03-14] vitreol: Died to stirge bite in Thornwood cave`

#### Scenario: Long summary truncation
- **WHEN** an event summary exceeds 120 characters
- **THEN** the summary SHALL be truncated to 120 characters
- **AND** no ellipsis or continuation marker SHALL be appended

### Requirement: Milestone output structure
The milestone builder SHALL return a string with header `@CAMPAIGN_MILESTONES={` followed by `events: [` array, one entry per line, closing `]` and `}`.

#### Scenario: Output structure
- **WHEN** 3 events qualify for inclusion
- **THEN** the output SHALL match this structure:
```
@CAMPAIGN_MILESTONES={
  events: [
    [2026-03-14] vitreol: Died to stirge bite in Thornwood cave
    [2026-03-14] vitreol: Resurrected at voidstone altar by Acheron
    [2026-03-15] party: Defeated Malarok the Corruptor
  ]
}
```

### Requirement: Empty result handling
The milestone builder SHALL return an empty string when no events qualify or when the input entity list is empty.

#### Scenario: No qualifying events
- **WHEN** all events for the given entities have `retrieval_score < 30` and `pinned = 0`
- **THEN** the function SHALL return `""` (empty string)

#### Scenario: Empty entity list
- **WHEN** `entity_ids = []`
- **THEN** the function SHALL return `""` (empty string)

### Requirement: Fail-open on database errors
The milestone builder SHALL catch all exceptions and return an empty string, logging a warning with category `narrator_memory`.

#### Scenario: Database connection failure
- **WHEN** the memory DB file does not exist or is corrupted
- **THEN** the function SHALL return `""` (empty string)
- **AND** log a warning: `MILESTONE_BUILD: Failed to query memory DB: <error>`

#### Scenario: Query execution error
- **WHEN** a SQL query fails during event retrieval
- **THEN** the function SHALL return `""` (empty string)
- **AND** log a warning with the error details

### Requirement: ASCII-only output
All milestone output SHALL contain only ASCII characters (no Unicode).

#### Scenario: Non-ASCII summary sanitization
- **WHEN** an event summary contains Unicode characters (e.g., em-dash, smart quotes)
- **THEN** the output SHALL replace or remove non-ASCII characters
- **AND** the result SHALL pass ASCII validation

### Requirement: Shared constants
The module SHALL define `MAX_MILESTONE_CHARS = 120`, `MAX_LOOKUP_CHARS = 150`, and `MILESTONE_SCORE_THRESHOLD = 30` at module level for reuse by Phase 2.

#### Scenario: Constants accessible
- **WHEN** `from core.memory.memory_retrieval import MAX_MILESTONE_CHARS, MAX_LOOKUP_CHARS, MILESTONE_SCORE_THRESHOLD`
- **THEN** the imports SHALL succeed
- **AND** values SHALL be 120, 150, and 30 respectively

