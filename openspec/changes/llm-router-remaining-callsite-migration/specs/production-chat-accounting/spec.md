# Spec Delta

## Purpose

Defines how migrated chat responses retain their existing usage and API-log effects while router receipts provide exactly-once accounting across the remaining production operations.

## ADDED Requirements

### Requirement: Existing Chat Accounting Is Preserved Once

Each successful migrated chat response SHALL produce exactly one event in every legacy usage or API-log consumer that the operation used before migration, and no event in consumers it did not previously use.

#### Scenario: An operation already records usage or an API log
- **WHEN** a migrated operation receives a successful provider response
- **THEN** each previously applicable legacy consumer SHALL receive exactly one event for that response
- **AND** its existing endpoint, context, and consumer ordering SHALL be preserved

#### Scenario: An operation had no legacy accounting consumer
- **WHEN** a migrated operation receives a successful provider response
- **THEN** migration SHALL NOT add a legacy tracker or API-log event for that operation

### Requirement: Router And Legacy Totals Do Not Double Count

Router accounting and existing legacy usage totals SHALL remain distinct, and one provider response SHALL NOT be delivered more than once to either applicable accounting surface.

#### Scenario: A response is observed through the facade
- **WHEN** one facade call produces a provider response
- **THEN** router usage SHALL record the response once
- **AND** any applicable legacy usage total SHALL record it once without replaying router totals into the legacy tracker

### Requirement: Provider Cost Provenance Is Preserved

Accounting SHALL preserve a valid provider-reported cost, including zero, and SHALL NOT fabricate a free or estimated amount when the response supplies neither cost nor a verified rate.

#### Scenario: Provider reports zero cost
- **WHEN** a successful response reports a finite non-negative cost of zero
- **THEN** accounting SHALL retain zero as an actual provider-reported cost
- **AND** it SHALL NOT substitute a static estimate

#### Scenario: Cost is unavailable
- **WHEN** a successful response has no usable provider cost and no verified rate
- **THEN** router accounting SHALL mark the call unpriced and cost-incomplete
- **AND** existing legacy consumers SHALL receive only the usage data they previously accepted

### Requirement: Failed Attempts Are Not Successful Usage Events

Provider errors and client-construction failures SHALL NOT be recorded as successful response usage events or API-log responses.

#### Scenario: A provider attempt fails
- **WHEN** a facade receipt represents a transport or construction failure rather than a response
- **THEN** error accounting MAY be recorded by the router
- **AND** no legacy successful-response usage event SHALL be emitted for that failed attempt
