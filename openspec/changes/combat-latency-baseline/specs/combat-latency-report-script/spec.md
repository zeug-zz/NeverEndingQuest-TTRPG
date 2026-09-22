## Purpose

Define the provider-free report contract for `scripts/combat_latency_report.py`.
The script turns opt-in JSONL trace data into bounded baseline tables for G1
target ratification without importing combat runtime clients or making network
calls.

## ADDED Requirements

### Requirement: The report script SHALL be provider-free

`scripts/combat_latency_report.py` SHALL read local trace input and compute its
output without provider clients, network requests, prompt generation, or game
state writes.

#### Scenario: Report runs offline

- **WHEN** the script is run against a local trace file with provider packages
  unavailable or network access disabled
- **THEN** it SHALL still produce a report or a bounded input diagnostic
- **AND** it SHALL make no provider call or game-state mutation

### Requirement: The report SHALL summarize baseline latency and work

For valid trace records, the report SHALL provide stage wall-clock timings,
provider-call counts and latency by site, available token totals, compression
call counts and cache hit rate, file read/write counts, and NL fast-path
hit/miss outcomes.

#### Scenario: Complete trace is reported

- **WHEN** the input contains the required event classes
- **THEN** the output SHALL include the corresponding aggregate sections
- **AND** aggregate values SHALL be derived only from observed records

### Requirement: The report SHALL summarize decision events

The report SHALL group decision events by `decision_point` and
`decision_source`, and SHALL summarize `decision_latency_ms` and
`provider_call_avoided` without interpreting or changing routing policy.

#### Scenario: Decision events are present

- **WHEN** the trace contains deterministic and LLM fallback decision events
- **THEN** the output SHALL report counts and latency summaries for each source
- **AND** it SHALL report provider-call avoidance separately

### Requirement: The report SHALL handle malformed or incomplete input explicitly

The script SHALL reject or boundedly diagnose malformed JSONL records, missing
required fields, unreadable files, and empty input. It SHALL NOT silently treat
missing measurements as zero when that would misrepresent the baseline.

#### Scenario: One malformed line is present

- **WHEN** a trace file contains valid records and a malformed JSONL line
- **THEN** the report SHALL identify the malformed input and its line context
- **AND** it SHALL either produce a clearly degraded report or exit non-zero
  according to the documented CLI contract

### Requirement: The report SHALL support the Phase 0 trace path

The script SHALL accept the trace path used by the baseline gate,
`debug/combat_turn_trace.jsonl`, through an explicit CLI argument or the
documented default. Its output SHALL be suitable for recording target
ratification or adjustment in the change review.

#### Scenario: Standard baseline command is used

- **WHEN** an operator runs `.venv/bin/python scripts/combat_latency_report.py --trace debug/combat_turn_trace.jsonl`
- **THEN** the script SHALL process that local trace path
- **AND** the output SHALL identify the input and fixture or mode summaries

### Requirement: Report generation SHALL not alter runtime state

The report script SHALL be read-only with respect to combat, character, party,
encounter, conversation, compression-cache, and world-time state. It SHALL
write no report artifact under `reports/` as part of this change.

#### Scenario: Report is generated after a smoke run

- **WHEN** the report is generated from the local trace
- **THEN** runtime state files SHALL remain unchanged
- **AND** the report SHALL contain only derived observations and diagnostics
