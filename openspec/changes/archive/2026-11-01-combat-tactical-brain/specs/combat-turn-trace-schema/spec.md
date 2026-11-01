# Spec Delta

## ADDED Requirements

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
