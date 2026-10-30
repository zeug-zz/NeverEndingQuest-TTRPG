# Spec Delta

## Purpose

Defines a provider-free source contract that inventories production chat operations and prevents future caller-owned chat transport from bypassing the facade.

## ADDED Requirements

### Requirement: Production Chat Inventory Is Refreshed

The G6 verification SHALL build its inventory from executable production Python source rather than rely on historical call-site totals.

#### Scenario: Inventory is generated for verification
- **WHEN** the production chat contract is checked
- **THEN** the inventory SHALL identify each executable chat transport call by file, enclosing operation, and source line
- **AND** test fixtures, documentation examples, and non-chat media operations SHALL NOT be counted as production chat calls

### Requirement: Raw Chat Transport Is Restricted To Infrastructure

Executable production `chat.completions.create` calls SHALL exist only in the router and the shared empty-response recovery transport boundary.

#### Scenario: A production module adds a direct chat call
- **WHEN** a production module outside the approved transport infrastructure contains an executable raw chat-completion call
- **THEN** the provider-free tripwire SHALL fail and identify the offending file and source location

#### Scenario: The remaining inventory is fully migrated
- **WHEN** the G6 contract is checked after migration
- **THEN** the only raw production chat call sites SHALL be the documented router and empty-response recovery infrastructure
- **AND** the unreferenced validator backup SHALL not remain as an untracked exception

### Requirement: Tripwire Covers Chat In Mixed-Purpose Modules

The production inventory SHALL include chat operations regardless of their containing module's other responsibilities, including action prediction and text generation for later media use.

#### Scenario: Action prediction and media-prompt chat are inventoried
- **WHEN** the source contract inventories production chat operations
- **THEN** ordinary action prediction and chat that produces text for image generation SHALL be checked for facade routing
- **AND** image, audio, speech, and other non-chat transport calls SHALL remain excluded

### Requirement: Tripwire Is Provider-Free

The inventory and bypass contract SHALL be testable without constructing a live provider client or making a network request.

#### Scenario: Contract tests run without provider access
- **WHEN** the tripwire and its negative fixtures are executed
- **THEN** all checks SHALL run from local source and fake inputs only
- **AND** the tests SHALL fail if the fixture's direct chat transport is not detected
