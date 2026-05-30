## ADDED Requirements

### Requirement: Bounded Event Retrieval
`_process_memory_lookup()` SHALL retrieve at most 8 events total across all requested entities.

#### Scenario: Top 8 events returned
- **WHEN** the lookup finds 15 events across 3 entities
- **THEN** only the top 8 by `retrieval_score` are included in the memory context

#### Scenario: Fewer than 8 events
- **WHEN** the lookup finds 3 events total
- **THEN** all 3 are included

### Requirement: Summary Truncation
Each event summary SHALL be truncated to `MAX_LOOKUP_CHARS` (150) characters.

#### Scenario: Long summary truncated
- **WHEN** an event summary is 300 characters
- **THEN** the output line contains only the first 150 characters

### Requirement: Entity Name Normalization
Entity names from the action parameters SHALL be normalized via `normalize_character_name()` before querying.

#### Scenario: Mixed case normalized
- **WHEN** the narrator requests `entities: ["Vitreol", "ACHERON"]`
- **THEN** queries use `vitreol` and `acheron`

### Requirement: Deduplication Across Entities
Events SHALL be deduplicated by `event_id` across all requested entities.

#### Scenario: Shared event not duplicated
- **WHEN** two entities share the same event (e.g., "party defeated Malarok")
- **THEN** the event appears only once in the output

### Requirement: Output Format
The memory context SHALL be formatted as a `[SYSTEM]` prefixed block with timestamped entries.

#### Scenario: Format matches contract
- **WHEN** 2 events are found
- **THEN** output is:
  ```
  [SYSTEM] Campaign memory -- Python-authoritative record:
    [2026-03-14] vitreol died to stirge bite in Thornwood cave
    [2026-03-14] vitreol resurrected at blighted grove voidstone altar
  ```

### Requirement: Empty Entities Handled
When `entities` is empty or missing, the function SHALL return immediately with no memory context.

#### Scenario: Empty entities list
- **WHEN** `parameters.entities` is `[]`
- **THEN** returns `create_return(needs_update=False)` with no `response_data`
