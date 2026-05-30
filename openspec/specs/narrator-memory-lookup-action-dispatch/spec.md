## Purpose

Define the action handler routing for narrator memory lookup. The `lookupMemory` action is dispatched through `process_action()` and processed by `_process_memory_lookup()`, following the same `create_return()` contract as all other action handlers.

## Requirements

### Requirement: Action Dispatch Routing
The action handler SHALL recognize `lookupMemory` as a valid action type and route it to `_process_memory_lookup()`.

#### Scenario: lookupMemory dispatched correctly
- **WHEN** the narrator emits `{"action":"lookupMemory","parameters":{"entities":["vitreol"],"query":"vitreol death history"}}`
- **THEN** `process_action()` routes to `_process_memory_lookup(parameters)`
- **AND** the function returns a dict with `status`, `needs_update`, and `response_data`

### Requirement: create_return Contract
`_process_memory_lookup()` SHALL use `create_return()` to match existing action handler conventions.

#### Scenario: Successful lookup uses create_return
- **WHEN** `_process_memory_lookup()` finds events for the requested entities
- **THEN** it returns `create_return(needs_update=False, response_data={"memory_context": "<formatted text>"})`

#### Scenario: Empty results use create_return
- **WHEN** `_process_memory_lookup()` finds no events
- **THEN** it returns `create_return(needs_update=False)` with no `response_data` key

### Requirement: Fail-Open on Error
`_process_memory_lookup()` SHALL catch all exceptions and return a safe continue response.

#### Scenario: DB error returns continue
- **WHEN** `get_entity_timeline()` raises an exception (missing DB, query failure)
- **THEN** `_process_memory_lookup()` logs a warning and returns `create_return(needs_update=False)`
- **AND** narration proceeds normally without memory context

### Requirement: ACTION_LOOKUP_MEMORY Constant
The module SHALL define `ACTION_LOOKUP_MEMORY = "lookupMemory"` as a module-level constant.

#### Scenario: Constant defined
- **WHEN** `action_handler.py` is imported
- **THEN** `ACTION_LOOKUP_MEMORY` equals `"lookupMemory"`
