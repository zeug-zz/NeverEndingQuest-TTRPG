# Spec Delta

## Purpose

Defines a bounded, isolated research capture for comparing approved mapping representations across one- and four-PC parties without changing production mapping behavior or claiming untested improvements.

## ADDED Requirements

### Requirement: Fixed research matrix preserves existing gates
The research capture MUST run exactly four independently reset rows in order B/P1, D/P1, D/P4, B/P4. It MUST leave existing gates, legacy profiles, goldens, defaults, and production behavior unchanged, and MUST make no A-arm, baseline-improvement, combat, or production-mapping claim.

#### Scenario: Fixed rows only
- **WHEN** the comparison matrix is evaluated
- **THEN** it contains exactly B/P1, D/P1, D/P4, and B/P4, each independently reset, with no altered existing gate artifacts or claims beyond this research scope

### Requirement: Shared facts and representation parity
Each row MUST use the same permitted canonical post-peaceful facts and identical native context. B MUST represent relationships explicitly; D MUST add ASCII plus the same concise relationships. Neither representation may add world facts or answer content.

#### Scenario: Equal-fact comparison
- **WHEN** B and D contexts are compared
- **THEN** their permitted semantic fact projections and native context are identical, with only the approved representation difference

#### Scenario: Content audit
- **WHEN** row inputs are audited for parity
- **THEN** both data hashes and semantic projections are checked against actual content, not identifiers alone

### Requirement: Display origin and unknown spatial semantics
The mapping query MUST anchor to the named room display, with north up, X east, and Y north; it MUST ask about the unique adjacent-east cell. Display coordinates MUST NOT imply distance, line of sight, cover, traversal, or a legal exit, and unlisted facts MUST remain unknown.

#### Scenario: Adjacent-east answer
- **WHEN** the narrator answers the approved spatial query
- **THEN** the named room-display origin and orientation are used, the unique adjacent-east cell is identified, and unsupported spatial or route properties remain unknown

#### Scenario: Path label is not an exit
- **WHEN** a map label suggests a route without an authored legal-exit fact
- **THEN** the response does not present that label as a traversable or legal exit

### Requirement: Character-knowledge boundaries
Hidden NPCs and hidden world facts MUST NOT enter mapping augmentation. Shared party facts MUST NOT establish a new per-PC knowledge engine or grant new PC knowledge.

#### Scenario: Hidden fact excluded
- **WHEN** mapping context is assembled
- **THEN** hidden NPC and world facts are absent, and shared party facts do not alter individual character knowledge

### Requirement: Current condition in narrator requests
Every actual narrator outbound request MUST contain exactly one current condition block, freshly replaced for each context build. Exact request and response bytes MUST be retained with fact hashes and state and active-PC provenance; missing, stale, duplicate, or wrong-condition context MUST prevent acceptance and MUST NOT produce a misleading PASS.

#### Scenario: Fresh narrator context
- **WHEN** a narrator request is sent after a context rebuild
- **THEN** it contains one current condition block and its exact request and response bytes are retained with matching provenance

#### Scenario: Invalid condition block
- **WHEN** an outbound narrator request has a missing, duplicate, stale, or mismatched condition block
- **THEN** the row is rejected and cannot receive PASS

#### Scenario: Non-narrator request
- **WHEN** a non-narrator provider request occurs
- **THEN** it is counted and retained, but is not required to contain a mapping condition block

### Requirement: Fixed route and party-state assertions
Each row MUST perform startup at CA01 and the seven-input route, with the specified party actors, persisted-state assertions, Mira response check, and exact one-minute canonical time check; missing mutations MUST prevent completion.

#### Scenario: Seven-input route
- **WHEN** a row completes its scripted route
- **THEN** startup and all seven inputs occur in the required sequence, with expected persisted location and active PC asserted at each step

#### Scenario: Mira response and wait
- **WHEN** the Mira dialogue and one-minute wait inputs are processed
- **THEN** Mira has a distinct narrator response and canonical persisted world-condition time advances by exactly one minute

#### Scenario: Missing state mutation
- **WHEN** any required location, active-PC, or time mutation is absent or incorrect
- **THEN** the row cannot be reported complete or passing

### Requirement: Fixed configured and observed model identity
All rows MUST use the fixed requested configured profile and direct model `gpt-6-luna/openai` with profile `dm_maincomplex`. Configured identity and response-observed identity MUST be recorded separately for all provider tasks. Unknown upstream identity MUST remain unknown. Unexpected retry, fallback, or identity drift MUST stop the row; quota or outage MUST be terminal without automatic rerun.

#### Scenario: Identity matches
- **WHEN** each request and response is captured
- **THEN** configured profile/model/provider and response-observed identity are recorded separately, including non-narrator provider tasks

#### Scenario: Identity drift or outage
- **WHEN** retry, fallback, identity drift, quota exhaustion, or provider outage is observed
- **THEN** the affected row stops and retains failure or blocked evidence without substitution or automatic rerun

### Requirement: Hard request and time budgets
The matrix MUST enforce fixed per-row and aggregate request, input, control, health-read, turn, row, and total-time ceilings. A persistent ledger MUST durably count each actual SDK attempt before transport, across restarts, and MUST fail closed if those calls cannot be observed. Socket turns MUST NOT substitute for SDK attempts; on failure or cap, stop and preserve FAIL or BLOCKED without replacement or extra calls.

#### Scenario: Cap reached
- **WHEN** any request, turn, row, or matrix cap is reached or actual SDK counting is unavailable
- **THEN** no subsequent request is sent and the evidence records FAIL or BLOCKED without a replacement row

#### Scenario: Restart cannot reset budget
- **WHEN** the runner or matrix is restarted
- **THEN** the persistent ledger retains prior actual attempts and enforces the same aggregate ceilings

### Requirement: Isolated and unique capture evidence
Runs MUST use a real isolated copy under `tmp/combat_capture/`, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository virtual environment, without touching port 8357, installed campaign, global runtime, configuration, or production state. The runner MUST reject unowned port 8360, sandbox symlink escape, invalid run ID or evidence path, and evidence-bundle overwrite or reuse before mutation. New unique bundles MUST be stored only under `tmp/router-rollout/mapping-research/<id>`.

#### Scenario: Safe isolated run
- **WHEN** a valid unique run is prepared
- **THEN** it uses only the prescribed sandbox and port, and writes a new evidence bundle under the prescribed research path

#### Scenario: Unsafe or reused destination
- **WHEN** a listener is unowned, a path escapes the sandbox, or a run ID or bundle is invalid or reused
- **THEN** preparation stops before mutation and preserves any existing evidence unchanged

### Requirement: Auditable evidence and role-specific verdicts
Evidence MUST retain identity, fixture and source provenance, inputs, controls, attempts, cost completeness, latencies, exact prompts and responses, per-step state, logs, traces, and stop lifecycle. It MUST exclude secret configuration, headers, and raw exception text. Unknown cost MUST remain null. Missing, degraded, or synthetic evidence MUST NOT pass; only the primary may issue PASS, FAIL, or BLOCKED, while evaluators may issue only READY_FOR_PRIMARY_REVIEW, FAIL, or BLOCKED.

#### Scenario: Complete live evidence
- **WHEN** a complete live bundle is evaluated
- **THEN** all listed evidence and provenance are cross-checked and the evaluator emits READY_FOR_PRIMARY_REVIEW, never PASS

#### Scenario: Missing or degraded evidence
- **WHEN** required evidence is missing, degraded, or synthetic, or a secret-bearing artifact would be recorded
- **THEN** the bundle is blocked or failed, no live PASS is emitted, and prohibited secret material is not retained

#### Scenario: Unknown cost
- **WHEN** cost data is unavailable
- **THEN** cost is recorded as null/unknown and is not represented as zero

### Requirement: Blinded review remains pending
Public transcripts and rendered maps MUST be blinded by condition label for human review. Fact scoring MUST remain separate from actual human ratings; ratings MUST NOT be fabricated, and socket evidence MUST NOT be presented as a client-usability conclusion. Until actual human review occurs, review and full research completion MUST remain pending; the four-row capture alone MUST NOT be called full research completion.

#### Scenario: Unrated capture
- **WHEN** live capture evidence exists but human ratings have not been collected
- **THEN** blinded review materials may be prepared, ratings remain pending, and no full-research-complete or client-usability conclusion is issued

#### Scenario: Human ratings
- **WHEN** actual human reviewers submit ratings
- **THEN** those ratings are retained separately from factual scores and are not synthesized or fabricated

### Requirement: Research-only execution guidance
The capture SHOULD reuse the existing Capture Arena rig and preserve exact artifacts needed for independent audit. It SHOULD keep evaluation focused on the bounded approved request rather than add generic research, security, or user-authorization frameworks. Execution MUST remain within the approved research-only comparison scope.

#### Scenario: Bounded evaluation
- **WHEN** the approved four-row comparison is evaluated
- **THEN** the evaluation remains limited to its evidence and acceptance contract and does not claim broader coverage
