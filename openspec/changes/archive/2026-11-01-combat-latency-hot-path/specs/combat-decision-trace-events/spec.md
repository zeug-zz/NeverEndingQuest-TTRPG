# Spec Delta

## ADDED Requirements

### Requirement: Validation routing outcomes SHALL be traceable

Each combat validation routing decision SHALL report whether LLM validation was skipped, its stable reason, and whether a provider call was avoided; the event SHALL NOT control routing.

#### Scenario: Deterministic prechecks allow a skip
- **WHEN** combat skips LLM validation after deterministic prechecks pass
- **THEN** the event SHALL record a deterministic source, a skip outcome, a reason, and `provider_call_avoided=true`

#### Scenario: Validation remains on the LLM path
- **WHEN** a deterministic precheck fails or an action is not eligible for skipping
- **THEN** the event SHALL record the non-skip outcome and its reason
- **AND** the event SHALL report `provider_call_avoided=false`

#### Scenario: Future Jev reason names remain reserved
- **WHEN** no Jev decision primitive is implemented
- **THEN** the runtime SHALL NOT emit `jev_residual_ok`, `jev_unavailable_fallback`, or `jev_low_confidence`
- **AND** those reason values SHALL remain reserved for separately authorized Jev work

### Requirement: NL PC-phase outcomes SHALL distinguish hit, miss, false positive, fallback, and unavailability

Eligible NL PC-phase decisions SHALL record a bounded outcome of hit, miss, false positive, or unavailable, and SHALL identify whether the existing LLM fallback ran; G5 reports SHALL calculate rates from observed events only.

#### Scenario: Supported action is applied deterministically
- **WHEN** an eligible parsed PC action is successfully applied
- **THEN** the event SHALL record a hit and `provider_call_avoided=true`

#### Scenario: Parser declines an action
- **WHEN** the parser does not recognize or fully parse an eligible action
- **THEN** the event SHALL record a miss and LLM fallback
- **AND** the action SHALL continue through the existing LLM path

#### Scenario: Parsed action cannot be applied
- **WHEN** the parser reports a handled action but deterministic application rejects it
- **THEN** the event SHALL record a false positive and LLM fallback
- **AND** the action SHALL continue through the existing LLM path

#### Scenario: Parser is unavailable
- **WHEN** the parser cannot be loaded for an eligible action
- **THEN** the event SHALL record `unavailable`, distinct from a parse miss
- **AND** the action SHALL continue through the existing LLM path

### Requirement: Deterministic `/att` hit decisions SHALL be traceable

The existing deterministic `/att` hit fast path SHALL emit the same bounded `combat_command_fast_path` decision event used by the `/dmg` fast path, including `provider_call_avoided=true`; this event is observational and SHALL NOT control routing.

#### Scenario: Attack hit records its fast-path decision
- **WHEN** `/att` resolves as a hit and records the pending-damage ledger event
- **THEN** the matching `combat_command_fast_path` decision SHALL be emitted before the hit branch returns
- **AND** it SHALL report `provider_call_avoided=true`
- **AND** the existing command result and routing behavior SHALL remain unchanged
