## ADDED Requirements

### Requirement: Transient Message Tag
Injected memory messages SHALL include `_transient_memory: True` to identify them for cleanup.

#### Scenario: Tag present on injected message
- **WHEN** memory results are injected into conversation history
- **THEN** the message dict contains `"_transient_memory": True`

### Requirement: Cleanup Previous Transient Messages
Before injecting new memory results, the function SHALL remove all previous `_transient_memory` messages from conversation history.

#### Scenario: Old transient removed
- **WHEN** conversation history contains a previous `_transient_memory` message
- **AND** new memory results are being injected
- **THEN** the old message is removed before the new one is appended

#### Scenario: Non-transient messages preserved
- **WHEN** conversation history contains regular user/assistant/system messages
- **THEN** those messages are NOT removed during cleanup

### Requirement: Conversation History Update Flag
When memory results are injected, the function SHALL set `needs_conversation_history_update = True`.

#### Scenario: Update flag set
- **WHEN** memory results are injected
- **THEN** `needs_conversation_history_update` is set to `True`

### Requirement: Injection Before Recursive Calls
Memory injection SHALL occur before any `needs_dm_response` or `needs_post_combat_narration` recursive calls.

#### Scenario: Injection precedes recursion
- **WHEN** memory results are pending and a recursive narration call is about to fire
- **THEN** the memory system message is already in conversation history when the recursive call executes
