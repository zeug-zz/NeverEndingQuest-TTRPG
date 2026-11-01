# combat-enemy-resolution-g5r Specification

## Purpose
Defines the repeated live G5R acceptance gate for deterministic enemy resolution in the existing one-PC and four-PC Capture_Arena scenarios.

## Requirements

### Requirement: G5R SHALL preserve the transferred G5 absolute targets

G5R SHALL preserve the G5 targets without waivers: exactly one supported-batch narration provider call and no validation provider call, median batch work-only time at or below 15.0 seconds (15000 ms), and no more than three raw gameplay/history file writes per batch.

#### Scenario: Supported batch meets all absolute targets
- **WHEN** a G5R batch is classified as resolver-supported
- **THEN** it SHALL contain exactly one narration provider call and zero combat-validation provider calls
- **AND** its work-only batch latency SHALL be included in the party-shape median and compared with 15.0 seconds (15000 ms)
- **AND** its raw gameplay/history file-write count SHALL be at most three

#### Scenario: Unsupported batch cannot establish resolver acceptance
- **WHEN** any scripted G5R batch is ineligible or uses whole-batch LLM fallback
- **THEN** the run SHALL retain its raw observations and deviation reason
- **AND** the G5R gate SHALL NOT report PASS for that party shape

#### Scenario: Absolute write target is exceeded
- **WHEN** any measured supported batch requires more than three gameplay/history file writes
- **THEN** G5R SHALL report the raw absolute write target as FAIL
- **AND** outcome normalization SHALL NOT reduce or waive that absolute count

### Requirement: G5R SHALL use three matched runs for each party shape

The gate SHALL capture three runs each for the existing 1-PC-party and 4-PC-party scenarios, reusing their action scripts, provider/model identity, fixture, seed, and measurement method. It SHALL summarize batch work-only latency and other continuous measures by the median of the three run-level observations for each party shape.

#### Scenario: Matched three-run party captures
- **WHEN** G5R evaluates a party shape
- **THEN** it SHALL require exactly three distinct, complete run bundles for that shape
- **AND** all bundles SHALL match the fixed scenario identity and measurement method
- **AND** it SHALL report each run result and the median without dropping an outlier

#### Scenario: A run is missing or has mismatched identity
- **WHEN** fewer than three complete bundles exist or any bundle differs in scenario, provider/model, seed, or measurement method
- **THEN** that party-shape gate SHALL be BLOCKED
- **AND** the report SHALL identify the missing or mismatched run without substituting zero

### Requirement: G5R SHALL retain raw regression observations

G5R SHALL retain raw provider-call and file-write observations and report them beside comparative deltas against the matched G5 reference. The existing G5 absolute targets SHALL always use raw measurements.

#### Scenario: Validator rejection retry is normalized
- **WHEN** the G5 reference and G5R runs include explicitly correlated validator-rejection retry attempts
- **THEN** the report SHALL show raw provider-call deltas unchanged
- **AND** the normalized provider-call delta SHALL subtract only the delta in those explicitly correlated retry provider requests

#### Scenario: Additional damaged PCs are normalized
- **WHEN** the number of distinct PCs whose character files change from enemy-batch damage differs between the matched G5 reference and G5R
- **THEN** the report SHALL retain the raw write delta
- **AND** the normalized write delta SHALL subtract the change in those distinct damaged-PC file targets
- **AND** no other write class SHALL be normalized away

#### Scenario: Outcome evidence is unavailable
- **WHEN** retry attribution or distinct damaged-PC outcome evidence is missing for either side of a comparison
- **THEN** the normalized comparison SHALL be BLOCKED rather than treating missing values as zero
- **AND** the raw comparison SHALL remain visible

#### Scenario: Outcome attribution is derived from bundle evidence

- **WHEN** the report computes outcome-normalized comparisons
- **THEN** distinct damaged-PC targets SHALL be derived from per-PC HP changes between the `step-NNN-before` and `step-NNN-after` snapshots around the enemy-batch step
- **AND** validator-rejection retries SHALL be derived from receipts/trace as `combat_main` attempts following a failed `combat_validation` in the same batch
- **AND** missing attribution SHALL BLOCK the comparison without invented values

### Requirement: G5R SHALL constrain outcome normalization

Provider normalization SHALL adjust only explicitly observed requests attributable to stochastic combat-validator rejection retries. Write normalization SHALL adjust only the delta in distinct PC character files changed by enemy-batch damage. Missing normalization evidence SHALL block a PASS.

#### Scenario: Only attributable outcomes are normalized

- **WHEN** the report computes comparative deltas against the matched G5 reference
- **THEN** it SHALL apply only the provider-retry and changed-PC-file adjustments defined by this requirement
- **AND** it SHALL retain raw and normalized deltas side by side

#### Scenario: Absolute targets are not normalized

- **WHEN** the report evaluates an absolute G5 target
- **THEN** it SHALL use raw observations without outcome normalization

### Requirement: G5R SHALL require all latency and regression targets to pass

Each party-shape verdict SHALL require complete captures, the raw absolute targets, the median latency threshold, and all applicable G5 no-regression checks to pass. The P1 work-only latency regression ceiling and P4 round-latency improvement target SHALL retain their existing G5 thresholds; outcome normalization SHALL NOT change the thresholds.

#### Scenario: P1 and P4 G5R targets pass
- **WHEN** all three matched runs for both party shapes are complete and every applicable raw, median, and outcome-normalized comparison meets its existing threshold
- **THEN** the overall G5R verdict MAY be PASS
- **AND** the report SHALL identify the P1 and P4 verdicts and the evidence bundles supporting them

#### Scenario: One target fails
- **WHEN** any applicable absolute, median, or normalized no-regression target fails
- **THEN** the affected party shape and overall G5R verdict SHALL be FAIL
- **AND** the report SHALL preserve the raw and normalized values and the decisive target

### Requirement: G5R evidence SHALL be isolated and reviewable

Every G5R run SHALL use a unique run ID and preserve scenario identity, current worktree/source identity, provider/model identity, expected-versus-observed assertions, raw traces, and report artifacts beneath `tmp/router-rollout/g5r/<run-id>/` before teardown. Gate tooling and the final verdict SHALL be orchestrator-reviewed; a driver exit code or provider-free result alone SHALL NOT establish PASS.

#### Scenario: Complete G5R run evidence is preserved
- **WHEN** a G5R capture completes or fails
- **THEN** its run-specific evidence SHALL remain under the G5R evidence root
- **AND** it SHALL record the party shape, seed, fixture identity, provider/model, worktree/source identity, and assertion outcomes

#### Scenario: Capture process exits successfully without required evidence
- **WHEN** the capture driver exits zero but a required assertion or evidence artifact is absent
- **THEN** the gate SHALL remain incomplete and SHALL report FAIL or BLOCKED
- **AND** no PASS SHALL be inferred from the process exit code

### Requirement: Resolver default SHALL remain disabled until primary-reviewed G5R PASS

The deterministic enemy-resolution flag SHALL remain OFF in shipped defaults until a primary reviewer accepts complete G5R evidence and records an overall PASS for both party shapes.

#### Scenario: G5R is blocked or fails
- **WHEN** the overall G5R verdict is BLOCKED or FAIL
- **THEN** the shipped resolver default SHALL remain OFF
- **AND** the existing generate-and-validate path SHALL remain available

#### Scenario: G5R receives primary-reviewed PASS
- **WHEN** the primary reviewer accepts complete P1 and P4 evidence and records G5R PASS
- **THEN** enabling the resolver default SHALL require a separate explicit rollout decision
- **AND** the rollback flag SHALL remain available
