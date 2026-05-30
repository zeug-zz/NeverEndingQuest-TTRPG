## Purpose

Define multi-site collection of memory context results in `process_ai_response()`. Memory context from `lookupMemory` actions is collected from all 6 `process_action()` call sites into a shared `_pending_memory_contexts` list, then injected as a single combined transient system message after all action loops complete.

## Requirements

### Requirement: Pending Contexts List
`process_ai_response()` SHALL initialize a `_pending_memory_contexts` list at the top of the function.

#### Scenario: List initialized
- **WHEN** `process_ai_response()` begins execution
- **THEN** `_pending_memory_contexts` is an empty list

### Requirement: Collection From All Call Sites
After each `process_action()` call, the function SHALL check for `response_data.memory_context` and append to `_pending_memory_contexts`.

#### Scenario: Memory context collected
- **WHEN** `process_action()` returns `{"response_data": {"memory_context": "..."}}`
- **THEN** the memory context string is appended to `_pending_memory_contexts`

#### Scenario: No memory context ignored
- **WHEN** `process_action()` returns a result without `memory_context`
- **THEN** `_pending_memory_contexts` is unchanged

### Requirement: Sequential Routing
`lookupMemory` SHALL be routed through the sequential `other_actions` loop, not the concurrent `ThreadPoolExecutor`.

#### Scenario: lookupMemory in other_actions filter
- **WHEN** the action type is `lookupMemory`
- **THEN** it is included in the `other_actions` set for sequential processing

### Requirement: Single Injection Point
After all action loops complete, if `_pending_memory_contexts` is non-empty, the function SHALL inject a combined transient system message.

#### Scenario: Combined injection
- **WHEN** 2 memory contexts were collected
- **THEN** they are joined with `"\n\n"` and appended as a single system message with `_transient_memory: True`

#### Scenario: No contexts, no injection
- **WHEN** `_pending_memory_contexts` is empty
- **THEN** no system message is injected
