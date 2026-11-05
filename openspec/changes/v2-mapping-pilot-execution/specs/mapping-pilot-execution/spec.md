# Spec Delta

## Purpose

Defines bounded, booked SP3 live execution and the evidence-backed SP4 review and owner decision gate for the frozen mapping pilot.

## ADDED Requirements

### Requirement: SP3 live execution requires a booked, non-overlapping window

The primary orchestrator MUST record an Overseer booking for port 8360 before any SP3 sandbox preparation or live request, and MUST record release after teardown. The SP3 window MUST NOT overlap Network live runs.

#### Scenario: SP3 has no booking or overlaps Network
- **WHEN** a live row is requested without a recorded booking or during an overlapping Network live run
- **THEN** execution is blocked before seeding, server launch, or provider request

#### Scenario: SP3 has a valid booking
- **WHEN** the primary starts a row within the recorded, non-overlapping window
- **THEN** the runner records the booking identity and proceeds only on the isolated `tmp/combat_capture/` copy at port 8360 with the repository virtual environment and `NEQ_OPEN_BROWSER=0`

### Requirement: Provider requests respect frozen attempt caps

Before every provider request, the runner MUST require known counters and enforce 800 attempts total and 35 attempts per row. Each issued request, retry, and classifier call counts as one attempt, including failed attempts.

#### Scenario: An attempt cap is reached or its counter is unknown
- **WHEN** the next request would exceed a count cap or any required attempt counter is unavailable
- **THEN** the request is refused and the actual counts and cap reason are preserved

### Requirement: Row and matrix live-time intervals follow the recorded interpretation

A row's live interval MUST begin at sandbox server launch and end at teardown completion. The six-hour matrix cap MUST sum row live intervals and exclude pauses between rows. Seeding before launch, evidence finalization or scoring after teardown, and booked-window elapsed MUST be recorded separately and excluded from the live-time caps.

#### Scenario: Lifecycle phases are timed
- **WHEN** a row is seeded, its sandbox is launched and torn down, and its evidence is finalized and scored
- **THEN** the live interval uses only launch through teardown completion and the other timestamps are recorded separately

### Requirement: Live-time cap stops preserve row outcomes

At 25 minutes of row live time or six hours of summed matrix live time, the runner MUST stop further live work, tear down the owned server, preserve evidence, and record the row as `FAIL` or `BLOCKED` under the stop rules. A time-cap stop MUST NOT be classified as `INFRASTRUCTURE` unless its evidenced cause independently qualifies.

#### Scenario: A row or matrix live-time cap is reached
- **WHEN** a row reaches 25 minutes live or the sum of row live intervals reaches six hours
- **THEN** no further live work proceeds and the teardown, counts, timestamps, evidence, outcome, and cap reason are recorded

### Requirement: The 30 preregistered slots have explicit outcomes and evidence

The runner MUST use the frozen `counterbalance.json` and scripts without changing fixtures, IDs, arms, party sizes, seeds, order, or budgets. Its resumable matrix ledger MUST finish with `PASS`, `FAIL`, `BLOCKED`, or `missing` for each of the 30 slots; every attempted row MUST retain its evidence bundle and score, while unrun slots MUST be explicitly marked missing with a reason.

#### Scenario: A planned row runs for either party size
- **WHEN** a booked SP3 run selects a frozen 1-PC or 4-PC row
- **THEN** it seeds that row, launches its arm in the sandbox, drives its frozen turn script through the socket driver, collects adapter turn evidence, router receipts, and shadow zone observations, writes the row bundle, and scores the row

#### Scenario: The matrix stops before all slots run
- **WHEN** execution stops or the reserve is exhausted before all 30 slots are attempted
- **THEN** every remaining slot is marked `missing` with its reason, and no slot or requirement is silently waived

#### Scenario: Driver exits successfully but evidence is degraded
- **WHEN** the socket driver exits zero while required evidence is degraded, absent, capped, or an assertion fails
- **THEN** the row is not marked `PASS`; it is recorded as `FAIL` or `BLOCKED` with preserved evidence and explanation

### Requirement: Reserve slots and infrastructure pauses follow preregistered rules

The runner MUST record `INFRASTRUCTURE`, `CONTENT/RESULT`, or `UNRESOLVED` before content review using only process, transport, provider-status, timing, and artifact-presence evidence. Only a pre-content infrastructure classification may activate the next reserve slot; the original row remains unchanged. Three consecutive infrastructure failures MUST pause the matrix for owner review.

#### Scenario: A row is eligible for replacement
- **WHEN** objective pre-content evidence establishes an eligible infrastructure failure
- **THEN** the next frozen reserve slot inherits that exact cell and repeat with its own seed and identity, without erasing or overwriting the original row

#### Scenario: A failure is content-related or unresolved
- **WHEN** a row has a response-quality failure or its infrastructure classification is ambiguous
- **THEN** it consumes no reserve slot; the row is retained as a result or `UNRESOLVED` pending owner adjudication

#### Scenario: Three infrastructure failures occur consecutively
- **WHEN** the third consecutive infrastructure failure is recorded
- **THEN** no further row starts until owner review, and the ledger preserves the pause point for resumption

### Requirement: Row execution is resumable and preserves isolated evidence

The runner MUST persist row identity, progress, cap counts, live-interval and other lifecycle timestamps, pre-content classification, evidence paths, and terminal status so an interrupted matrix can resume without replaying a completed row or replacing prior evidence. It MUST use a fresh sandbox copy for each row, preserve raw live evidence before teardown, finalize evidence and scoring after teardown, and never inspect or use port 8357 or the installed campaign.

#### Scenario: An interrupted matrix resumes
- **WHEN** the primary resumes from a saved ledger after interruption
- **THEN** completed rows and their evidence remain immutable and execution continues only from eligible unstarted or explicitly reserved slots

#### Scenario: Row teardown and finalization complete
- **WHEN** the owned server teardown completes and row evidence is finalized and scored
- **THEN** the runner records teardown completion as the end of the live interval, records later finalization timestamps, and preserves the row evidence without deleting or overwriting it

### Requirement: Live transcript review is partially blinded and ratings remain human input

The SP4 review packet MUST use opaque response IDs and withhold arm, row order, model/provider metadata, and fixture answer keys until ratings are locked. It MUST disclose that visible ASCII sketches can reveal format and therefore blinding is partial. Ratings MUST follow the frozen rubric, keep factual scoring separate, and use `not rateable` for missing or truncated responses; no rating may be inferred.

#### Scenario: Transcript packets are prepared for the owner
- **WHEN** live transcripts are available for SP4 review
- **THEN** packets contain only the blinded transcript and opaque response ID, with the condition key held separately until the owner locks ratings

#### Scenario: A transcript is missing or truncated
- **WHEN** the owner reviews an unavailable or truncated transcript
- **THEN** its rating is `not rateable` rather than an imputed score

### Requirement: SP4 report covers preregistered questions and preserves missing human inputs

The SP4 report MUST aggregate available rows with the existing scoring contract, cover Q1-Q6, and give `retain`, `revise`, `reject`, or `inconclusive` recommendations for the exploration packet, format, zone combat, backfill, and shared map. Q6 MUST report token, latency, retry, and route-confound evidence without adding a new threshold. Missing owner ratings or the D1 audit MUST be labelled `pending/not provided`; Stage 1 MUST be recorded as `waived`, never as ratings.

#### Scenario: Owner inputs are absent
- **WHEN** the report is generated without live-transcript ratings, M1 ratings, or an owner D1 audit
- **THEN** each absent input is labelled `pending/not provided`, no rating or audit value is fabricated, and decisions depending on it remain inconclusive or pending

#### Scenario: Owner inputs are available
- **WHEN** valid owner inputs and the live evidence are available
- **THEN** the report records their provenance, reports Q1-Q6 and all five recommendations, and produces concrete S1, S2, SC1, S3, and S4 inputs using only the preregistered decision rules

#### Scenario: D1 handoff is prepared
- **WHEN** D1 proposal and audit evidence are assembled for SP4
- **THEN** the report includes a Module Builder module-data requirements and gap list, distinguishes observed claims from owner-audited judgments, and leaves absent audit conclusions pending

### Requirement: The spatial ADR and owner gate remain proposals until accepted

SP4 MUST produce a draft ADR under `adrs/` using the next available zero-padded four-digit ADR identifier and repository format, with `Status: Proposed`. It MUST address Python spatial authority, audience-specific projections, schematic versus metric facts, observed versus enforced legality, and the preregistered close-enough rule. Drafting or recording a gate MUST NOT imply ADR acceptance.

#### Scenario: The draft ADR is created
- **WHEN** SP4 produces the spatial decision materials
- **THEN** the proposed ADR and ADR index identify the decision as awaiting explicit owner acceptance

#### Scenario: The owner gate records its choices
- **WHEN** the owner chooses the format, combat granularity/enforcement level, and data pipeline
- **THEN** the gate record captures those choices and evidence, while the ADR remains Proposed until separately accepted

### Requirement: Pilot execution preserves production boundaries and arm A

SP3/SP4 tooling and tests MUST remain research-only: no production default, core hook, `model_config.py`, repository `modules/`, published catalog, installed campaign, web/client behavior, or party-size gate may change. Provider-free verification MUST make no provider calls or start a server; arm A MUST remain a no-op, and both 1-PC and 4-PC paths MUST be covered.

#### Scenario: Provider-free verification runs
- **WHEN** the mapping-pilot test suite runs
- **THEN** it uses injected boundaries without provider calls or server startup, covers 1-PC and 4-PC rows, and proves arm A remains unchanged

#### Scenario: A proposed change crosses a production boundary
- **WHEN** implementation would modify a prohibited production path or activate a core hook
- **THEN** the change is blocked rather than expanding the approved research-only scope
