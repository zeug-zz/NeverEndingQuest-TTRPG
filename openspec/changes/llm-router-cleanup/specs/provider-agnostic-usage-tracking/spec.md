# Spec Delta

## ADDED Requirements

### Requirement: Chat usage SHALL preserve response cost provenance
Each successful chat response SHALL be classified as actual, estimated, or unpriced without losing observed token counts.

#### Scenario: Provider reports a valid cost including zero
- **WHEN** a chat response contains a finite non-negative reported cost
- **THEN** the cost SHALL be recorded as actual exactly once
- **AND** no configured-rate estimate SHALL be added for that response

#### Scenario: Verified resolved-model rates are available
- **WHEN** a response has no valid reported cost, complete token usage, and verified rates matching its concrete resolved model
- **THEN** the known cost SHALL be recorded as estimated
- **AND** the estimate SHALL NOT use rates for another model or for `openrouter/auto`

#### Scenario: Chat response is not priceable
- **WHEN** a response has no valid reported cost and no verified matching resolved-model rates
- **THEN** its observed token counts SHALL be retained
- **AND** it SHALL be recorded as unpriced with incomplete cost coverage, not as a zero-cost or blended estimate

### Requirement: Session and week rollups SHALL reconcile chat receipts once
Session and rolling-week chat totals SHALL include each successful router response once and expose known-cost provenance and unpriced completeness.

#### Scenario: Actual and estimated chat responses are aggregated
- **WHEN** actual and verified-estimated chat responses are observed in a session and rolling-week window
- **THEN** `session_cost_usd` and `week_cost_usd` SHALL equal the sums of their actual and estimated costs
- **AND** `session_cost_actual_usd`, `session_cost_estimated_usd`, `week_cost_actual_usd`, and `week_cost_estimated_usd` SHALL preserve those subtotals

#### Scenario: Unpriced chat response affects completeness
- **WHEN** a chat response in either window is unpriced
- **THEN** the corresponding `session_unpriced_calls` or `week_unpriced_calls` SHALL increase
- **AND** the corresponding `session_cost_complete` or `week_cost_complete` SHALL be false without adding an invented amount to the known-cost subtotal

#### Scenario: Receipt forwarding and media events remain distinct
- **WHEN** a router chat receipt and a cost-only image or other existing media event are tracked
- **THEN** the chat receipt SHALL affect token totals and cost totals exactly once
- **AND** the media event SHALL remain in cost totals without changing chat token totals or being counted again as a chat receipt

### Requirement: `/usage` SHALL report router and session/week accounting
The read-only `/usage` command SHALL report router usage and reconciled session/week usage with cost provenance and completeness.

#### Scenario: Usage is requested during a session
- **WHEN** the user enters `/usage`
- **THEN** the response SHALL include router token/call totals, known cost subtotal, unpriced-call count, and cost completeness
- **AND** it SHALL include session and rolling-week token totals, actual and estimated cost subtotals, unpriced counts, and completeness
- **AND** it SHALL make no provider request or gameplay-state mutation
