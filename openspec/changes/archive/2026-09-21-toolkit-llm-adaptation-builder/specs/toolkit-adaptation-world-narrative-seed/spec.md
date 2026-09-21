## Purpose

Defines the bounded world-narrative context that may guide adaptation while preventing an LLM build from directly mutating campaign canon or mechanical truth.

## ADDED Requirements

### Requirement: World context is bounded and read-only

When world-narrative context is enabled, the adaptation author MUST receive a bounded versioned pack containing only approved campaign model, active pressure, registry, and module-seed fields.

#### Scenario: Seed context available

- **WHEN** an approved world-narrative seed and campaign context are available
- **THEN** the adaptation request includes the bounded pack with its version and hash

#### Scenario: Seed context unavailable

- **WHEN** the seed database or retrieval provider is unavailable
- **THEN** adaptation continues with a recorded unavailable status or fails only if the selected policy requires world grounding

### Requirement: World hooks are proposals, not direct canon writes

The adaptation author MAY propose world hooks, thread continuations, and module narrative seeds, but the response MUST NOT directly apply those proposals to campaign canon or mechanical state.

#### Scenario: Proposed continuation

- **WHEN** the adaptation response includes a candidate thread continuation
- **THEN** Python persists it as an adaptation proposal with provenance

#### Scenario: Direct canon mutation

- **WHEN** the adaptation response attempts to alter campaign world state, registry state, or mechanical fields directly
- **THEN** Python rejects the mutation and preserves the prior canonical state

### Requirement: World context provenance is auditable

An adaptation using world context MUST record the seed version, context hash, selected module context, and whether any world hooks were proposed.

#### Scenario: Grounded adaptation report

- **WHEN** an adaptation completes using world context
- **THEN** its report identifies the exact context version and hash used

#### Scenario: Generic fallback report

- **WHEN** no world context was available
- **THEN** its report records the fallback status and does not claim world-seed grounding
