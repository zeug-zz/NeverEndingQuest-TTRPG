# narrator-memory-milestone-injection Specification

## Purpose
TBD - created by archiving change narrator-memory-milestone-injection. Update Purpose after archive.
## Requirements
### Requirement: Entity ID resolution from party tracker
The system SHALL provide `_resolve_party_entity_ids(party_tracker_data: Dict) -> List[str]` in `main.py` that extracts normalized entity IDs from `partyMembers` and `partyNPCs`.

#### Scenario: PC entity extraction
- **WHEN** `party_tracker_data = {"partyMembers": ["Acheron", "Vitreol"]}`
- **THEN** the function SHALL return `["acheron", "vitreol"]` (normalized)

#### Scenario: NPC entity extraction (string form)
- **WHEN** `party_tracker_data = {"partyNPCs": ["Scout Kira", "Liri"]}`
- **THEN** the function SHALL return `["scout_kira", "liri"]` (normalized)

#### Scenario: NPC entity extraction (dict form)
- **WHEN** `party_tracker_data = {"partyNPCs": [{"name": "Scout Kira"}, {"name": "Liri"}]}`
- **THEN** the function SHALL return `["scout_kira", "liri"]` (normalized)

#### Scenario: Deduplication
- **WHEN** the same entity appears in both `partyMembers` and `partyNPCs`
- **THEN** the entity SHALL appear exactly once in the output

### Requirement: Milestone injection after singularity guard
The system SHALL inject milestones into `messages_to_send` after the singularity guard (line 5248) and before transient correction (line 5251) in `main.py:get_ai_response()`.

#### Scenario: Injection point
- **WHEN** `get_ai_response()` executes with `validation_retry_count = 0`
- **AND** milestones are available
- **THEN** milestones SHALL be appended to the main system prompt message (identified by `@DUNGEON_MASTER` marker)
- **AND** injection SHALL occur after `dedupe_main_system_prompt_messages()` call

### Requirement: Append to main system prompt
The system SHALL append milestone content to the existing main system prompt message, not inject as a separate system message.

#### Scenario: Append pattern
- **WHEN** the main system prompt contains `@DUNGEON_MASTER` marker
- **AND** milestones block is non-empty
- **THEN** the milestones SHALL be appended to that message's content with `\n\n` separator
- **AND** no new system message SHALL be added to `messages_to_send`

### Requirement: Skip injection on validation retries
The system SHALL skip milestone injection when `validation_retry_count > 0`.

#### Scenario: First attempt injection
- **WHEN** `validation_retry_count = 0`
- **AND** milestones are available
- **THEN** milestones SHALL be injected

#### Scenario: Retry skip
- **WHEN** `validation_retry_count = 1` (or higher)
- **THEN** milestones SHALL NOT be injected
- **AND** no database query SHALL occur

### Requirement: Fail-open on injection errors
The system SHALL catch all exceptions during milestone injection and continue narration without milestones, logging a warning.

#### Scenario: Entity resolution failure
- **WHEN** `_resolve_party_entity_ids()` raises an exception
- **THEN** narration SHALL continue without milestones
- **AND** log: `MILESTONE_INJECT: Failed to resolve entity IDs: <error>`

#### Scenario: Milestone build failure
- **WHEN** `build_campaign_milestones()` raises an exception
- **THEN** narration SHALL continue without milestones
- **AND** log: `MILESTONE_INJECT: Failed to build milestones: <error>`

### Requirement: Transient-only injection
Milestone content SHALL NOT be persisted to `conversation_history.json`. It SHALL be rebuilt fresh on each narrator call.

#### Scenario: No persistence
- **WHEN** milestones are injected into `messages_to_send`
- **AND** the narrator call completes
- **THEN** `conversation_history.json` SHALL NOT contain the milestone block
- **AND** the next narrator call SHALL rebuild milestones from the memory DB

### Requirement: Export in __init__.py
The function `build_campaign_milestones` SHALL be exported in `core/memory/__init__.py` `__all__` list.

#### Scenario: Import from package
- **WHEN** `from core.memory import build_campaign_milestones`
- **THEN** the import SHALL succeed
- **AND** the function SHALL be callable

