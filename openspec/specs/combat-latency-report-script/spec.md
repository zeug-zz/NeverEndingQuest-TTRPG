# combat-latency-report-script Specification

## Purpose
Define the provider-free report contract for `scripts/combat_latency_report.py`.
The script turns opt-in JSONL trace data into bounded baseline tables for G1
target ratification without importing combat runtime clients or making network
calls.

## Requirements

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
hit/miss outcomes. For G5R input it SHALL additionally report, by party shape,
the three run-level enemy-batch work-only latencies and their median, raw
provider calls, raw gameplay/history writes per batch, resolver eligibility,
and the normalized provider-call and write comparisons. Raw observations SHALL
remain visible beside every normalized value.

#### Scenario: Complete trace is reported

- **WHEN** the input contains the required event classes
- **THEN** the output SHALL include the corresponding aggregate sections
- **AND** aggregate values SHALL be derived only from observed records

#### Scenario: Three G5R runs are summarized

- **WHEN** the input contains three complete, identity-matched run bundles for
  a party shape
- **THEN** the report SHALL show every run-level batch work-only latency and
  the median of those three values
- **AND** it SHALL show raw and outcome-normalized regression metrics as
  separate values

#### Scenario: Supported batch call count is normalized

- **WHEN** the trace identifies a batch as `resolver_supported`
- **THEN** the report SHALL derive its normalized resolver call count only from
  correlated narration-only provider events
- **AND** it SHALL report a missing narration event or any validation event as
  a deviation rather than silently counting one call

#### Scenario: Physical batch writes are reported

- **WHEN** the trace contains correlated gameplay/history write events for a
  batch
- **THEN** the raw batch write count SHALL count each physical write event
- **AND** grouped persistence helpers SHALL NOT collapse multiple writes into
  one reported write

#### Scenario: Outcome attribution is computed from local bundle evidence

- **WHEN** the report computes normalized provider-call and damaged-PC write deltas
- **THEN** changed-PC targets SHALL be derived from per-PC HP differences between the enemy-batch `step-NNN-before` and `step-NNN-after` snapshots
- **AND** validator-rejection retry requests SHALL be derived from receipts/trace as `combat_main` attempts following a failed `combat_validation` in the same batch
- **AND** the report SHALL remain provider-free

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
missing measurements as zero when that would misrepresent the baseline. For
G5R it SHALL require exactly three complete run bundles per party shape and
complete retry-attribution and damaged-PC outcome evidence for each normalized
comparison; missing data SHALL be BLOCKED, not zero-filled.

#### Scenario: One malformed line is present

- **WHEN** a trace file contains valid records and a malformed JSONL line
- **THEN** the report SHALL identify the malformed input and its line context
- **AND** it SHALL either produce a clearly degraded report or exit non-zero
  according to the documented CLI contract

#### Scenario: G5R run bundle or outcome evidence is incomplete

- **WHEN** fewer than three complete run bundles exist or normalized outcome
  evidence is missing
- **THEN** the report SHALL mark the affected party-shape comparison BLOCKED
- **AND** it SHALL preserve available raw values without substituting zero
- **AND** missing attribution SHALL stop the builder from asserting a normalized comparison

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

### Requirement: The report SHALL summarize G5T commander observations

The report SHALL summarize G5T P1/P4 latency, synchronous calls by plan/narration/validation site, background standing-order calls by distinct site, per-batch writes, plan legality, and behavioral evidence. Optional standing-order counts and outcomes SHALL be separate. Existing G1/G3/G4/G5/G5R outputs SHALL remain unchanged.

#### Scenario: Three G5T runs are summarized

- **WHEN** the input contains three valid G5T captures for each party shape
- **THEN** the report SHALL show all three raw latency observations and the median for each shape
- **AND** it SHALL show raw call and write counts for each observed batch
- **AND** it SHALL summarize plan choice legality only from validation records

#### Scenario: G5T target is evaluated

- **WHEN** complete G5T records are present
- **THEN** the report SHALL identify primary-acceptance batches exceeding two synchronous provider calls, any synchronous validation call, raw writes above one history write plus one encounter write plus one write per distinct character whose canonical state changed, or a party-shape median exceeding 15000 ms
- **AND** it SHALL report background standing-order counts separately, with no more than two such requests per batch
- **AND** it SHALL expose the observations supporting each comparison
- **AND** a missing measurement SHALL be diagnosed rather than treated as zero

#### Scenario: Optional standing-order results are present

- **WHEN** G5T input includes background standing-order records
- **THEN** the report SHALL separate initial/re-plan counts and completed, failed, cancelled, expired, unavailable, and not-requested outcomes from primary synchronous results
- **AND** optional standing-order evidence SHALL NOT waive or replace primary G5T targets

### Requirement: G5T report SHALL expose self-preservation evidence

For G5T captures, the provider-free report SHALL distinguish observed `fled` and `surrendered` outcomes using bounded traces and authoritative encounter snapshots. It SHALL report whether the flee used Disengage without an attack, whether the creature was removed from later actor/target menus, and whether the existing exit/XP path completed when all enemies were defeated.

#### Scenario: Flight and surrender observations are present
- **WHEN** G5T records contain per-creature self-preservation outcomes
- **THEN** the report SHALL show the outcome and matching `defeatReason` for each observed creature
- **AND** it SHALL expose the evidence for actor/target removal and existing lifecycle completion

#### Scenario: Required self-preservation evidence is missing
- **WHEN** a required capture lacks an authoritative flee or surrender observation
- **THEN** the report SHALL diagnose the missing evidence
- **AND** it SHALL NOT claim the corresponding G5T behavior assertion passed
