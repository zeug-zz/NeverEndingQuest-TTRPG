# Spec Delta

## ADDED Requirements

### Requirement: Existing report behavior SHALL remain unchanged without G5

When G5 comparison is not selected, the provider-free report SHALL preserve the existing G1 report output and default latency-script behavior byte-for-byte.

#### Scenario: Historical report command is used
- **WHEN** the existing report command is run without G5 inputs
- **THEN** its G1 output and default behavior SHALL remain byte-for-byte unchanged
- **AND** no G5 comparison fields SHALL be added to that output

### Requirement: The report SHALL compare equivalent G5 before and after evidence

The provider-free report SHALL compare distinct G5 before and after bundles only when fixture, party size, seed, provider/model identity, and measurement method match; G1 evidence SHALL remain historical and separate.

#### Scenario: Equivalent current-model bundles are available
- **WHEN** before and after bundles contain matching 4-PC and 1-PC fixture identities using direct OpenAI `gpt-6-luna`
- **THEN** the report SHALL compare the matching runs by fixture and action/batch
- **AND** it SHALL retain each distinct run identifier

#### Scenario: The G5 before reference is missing or incompatible
- **WHEN** the required before bundle is absent, timed out, degraded, or differs in fixture, seed, provider/model, or measurement method
- **THEN** the report SHALL classify the comparison as `BLOCKED`
- **AND** it SHALL NOT claim a structural latency improvement

#### Scenario: Archived G1 evidence is present
- **WHEN** historical G1 results are included for context
- **THEN** the report SHALL label them as historical gpt-5.6-luna evidence
- **AND** it SHALL NOT substitute or relabel them as the G5 current-model before reference

### Requirement: The G5 report SHALL evaluate fixed latency and work targets

The report SHALL evaluate the ratified latency, provider-call, file-write, per-round improvement, and 1-PC non-regression targets from observed G5 evidence without changing their thresholds.

#### Scenario: All after-capture targets are met
- **WHEN** the after evidence reports LLM PC-action p50 at most 8 seconds, deterministic PC-action p50 below 1 second, enemy-batch p50 at most 15 seconds, at most 1 fast-path or 2 LLM calls per uncontested PC action, exactly 1 call per enemy batch, at most 3 writes per turn, at least 30 percent lower 4-PC per-round latency than the matching before run, P1 work-only p50 at most 1.10 times the before reference, and no increase in P1 provider calls or file writes
- **THEN** the report SHALL mark those targets as passing
- **AND** it SHALL report each metric and the comparison inputs

#### Scenario: Any fixed target is missed
- **WHEN** valid comparable after evidence misses any fixed latency, call, write, per-round, or 1-PC target
- **THEN** the G5 verdict SHALL be `FAIL`
- **AND** the report SHALL identify the failed target without adjusting its threshold

#### Scenario: A phase increases provider calls or writes
- **WHEN** a corresponding measured phase has more provider calls or file writes after optimization than in its before run
- **THEN** the G5 verdict SHALL be `FAIL`
- **AND** the report SHALL identify the phase and work-unit attribution

#### Scenario: Required after evidence is degraded or incomplete
- **WHEN** a required after run times out, reaches its capture cap, is degraded, or lacks a required measurement
- **THEN** the G5 verdict SHALL be `BLOCKED`
- **AND** the report SHALL NOT treat a missing measurement as zero

### Requirement: The G5 report SHALL expose deterministic and routing rates

The report SHALL summarize validation-skip and NL fast-path hit, miss, false-positive, LLM-fallback, and unavailable rates from observed decision events, and SHALL separate work-only latency from quiet-window elapsed time.

#### Scenario: Deterministic and fallback outcomes are observed
- **WHEN** the trace contains skipped validation, NL hits, misses, false positives, LLM fallbacks, or unavailable outcomes
- **THEN** the report SHALL count and calculate rates for each observed outcome separately
- **AND** it SHALL report work-only and quiet-window timing separately

#### Scenario: A routing outcome has no events
- **WHEN** no event for a routing outcome is present in the trace
- **THEN** the report SHALL represent its count/rate as unavailable rather than zero
