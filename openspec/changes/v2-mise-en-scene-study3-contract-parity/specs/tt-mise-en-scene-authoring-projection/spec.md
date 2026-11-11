# Spec Delta

## ADDED Requirements

### Requirement: Study 3 output rules SHALL be traceable to the request (R13)

Every output-facing validator rule SHALL map to its exact source in rendered messages, the injected schema, or canonical inputs and to its corresponding validator assertion. Host safety and integrity checks SHALL be identified separately.

#### Scenario: Rule map covers every output-facing constraint
- **GIVEN** the Study 3 output contract and validator rules
- **WHEN** the auditable rule map is reviewed
- **THEN** it SHALL map field names and closed-object boundaries, exact identities and namespace, stage roles/order/uniqueness, permitted predicates/values, reference scope, public-fact and claim-span binding, agency values, per-field/aggregate limits, unknown keys, stale hashes, overwrite protection, and protected unknowns to their request/schema/input source and validator assertion

#### Scenario: Undisclosed output rule is introduced
- **GIVEN** a validator adds an output-facing restriction without a corresponding request, schema, or canonical-input rule
- **WHEN** the semantic parity checks run
- **THEN** the checks SHALL fail and identify the unmapped rule

#### Scenario: Request declaration is removed
- **GIVEN** a request message or injected schema omits a declared output-facing rule while its validator enforcement remains
- **WHEN** the semantic parity checks run
- **THEN** a negative mutation SHALL fail the checks without relying only on token-string matching or claiming formal proof of natural-language completeness

#### Scenario: Rule-coverage evidence does not overclaim finite examples
- **GIVEN** the rule inventory, bidirectional semantic mutations, and diagnostics over the three frozen Study 2 deltas are reviewed
- **WHEN** parity evidence is summarized
- **THEN** these SHALL be reported as complementary coverage evidence and SHALL NOT be described as proof that no conceivable hidden rule exists

#### Scenario: Host safety is not exposed as model contract
- **GIVEN** a check protects local paths, canonical-file integrity, approval state, allocation state, credentials, transport identity, or network behavior
- **WHEN** the rule map is reviewed
- **THEN** the check SHALL be classified as host safety/integrity and SHALL NOT require disclosing credentials or local path internals in the request

### Requirement: Study 3 authored IDs and stage relations SHALL be explicit (R14)

Study 3 SHALL declare the module-qualified `study3-authored` fact-ID namespace in the system prompt and enforce the same escaped, anchored module-specific pattern in the injected schema. Source/base fact IDs SHALL remain distinct from authored IDs; both required stage-relation values SHALL be literal JSON boolean `true`.

#### Scenario: Authored fact ID uses the declared namespace
- **GIVEN** a request is built for a scene with a module ID from its frozen topology
- **WHEN** the exact system message and injected output schema are rendered
- **THEN** the message SHALL declare `<module_id>:fact:study3-authored:<suffix>` and the schema pattern SHALL match that module-qualified namespace while rejecting Study 2 and base-fact namespaces

#### Scenario: Stage relation is represented by boolean true
- **GIVEN** an authored `approach_to_threshold` or `threshold_to_focal` fact is returned
- **WHEN** its subject, object, and value are validated against the bound stage roles
- **THEN** the subject/object roles SHALL match and the value SHALL be exactly boolean `true`, not a typed reference or another truthy value

#### Scenario: Source and authored identities do not collide
- **GIVEN** an authored fact attempts to reuse a frozen source/base fact ID or duplicate another authored ID
- **WHEN** the delta is validated
- **THEN** validation SHALL reject the overwrite or duplicate before hydration

### Requirement: Study 3 delta fields and semantic constraints SHALL be closed (R18)

The Study 3 output SHALL conform to the closed delta schema and semantic contract declared in the exact request. Invalid fields, references, values, or bounds SHALL be rejected before hydration. Normal contract validation MAY stop at its first invalid condition; the separate Study 3 diagnostic mode SHALL collect every independently evaluable violation as specified by R20.

#### Scenario: Output contract admits only the declared delta
- **GIVEN** a response contains an unknown root or nested key, a source/topology replacement, an unsupported predicate or value shape, a duplicate key, or a non-finite value
- **WHEN** Study 3 contract validation runs
- **THEN** it SHALL reject the response before hydration with a stable metadata-only diagnostic
- **AND** it SHALL accept no canonical base-fact, topology, or protected-unknown overwrite

#### Scenario: Delta envelope, reference, and field bounds match the schema
- **GIVEN** a Study 3 delta is rendered and validated
- **WHEN** its structure and bounds are checked
- **THEN** its only root fields SHALL be `schema`, `input_refs`, `fixture_deltas`, `stage_role_bindings`, `claims`, and `arrival_prose`
- **AND** `input_refs` SHALL contain only the exact scene ID and bound `source_packet`, `expected_bundle`, `topology`, and `gate_canonical_context` references with exact IDs and lowercase 64-character SHA-256 values
- **AND** each reference ID SHALL be 1-512 characters; authored fact IDs SHALL be at most 256 characters; claim and arrival-segment IDs SHALL be at most 512 characters
- **AND** the payload SHALL be at most 65,536 bytes and contain at most 64 authored facts
- **AND** each of `approach`, `threshold`, `focal_anchor`, and `usable_space` SHALL contain 1-16 unique topology candidate IDs
- **AND** there SHALL be exactly three claims groups and three arrival segments in `approach`, `threshold`, `focal` order, with at most 32 claims per group and 1-512 characters of text per arrival segment

#### Scenario: Predicate, value, and reference scope match the contract
- **GIVEN** an authored fact or reference is validated
- **WHEN** its predicate, value, subject, object, and references are checked
- **THEN** predicates SHALL be limited to `approach_to_threshold`, `threshold_to_focal`, `usable_space`, `light_gradient`, `sound_gradient`, `weather_gradient`, and `visible_affordance`
- **AND** values SHALL be strings of at most 512 characters, booleans, null, or closed `entity_ref`/`fact_ref` objects
- **AND** entity references SHALL resolve to the bound topology and fact references SHALL resolve only to public base or Study 3 authored facts
- **AND** arbitrary objects and arrays SHALL be rejected

#### Scenario: References, stage bindings, claims, and limits are checked
- **GIVEN** a delta has a stale input hash, an unbound reference, duplicate role ID, wrong stage relation/order, invalid public claim reference/span, invalid invitation agency, or a field/aggregate limit violation
- **WHEN** semantic validation runs
- **THEN** it SHALL reject the first invalid contract condition before hydration
- **AND** each rule and bound SHALL appear in the exact rendered request/schema and auditable rule map
- **AND** the first-invalid behavior SHALL apply only to normal contract validation, not the collect-all diagnostic mode

#### Scenario: Valid invitation leaves choice and success with the player
- **GIVEN** an arrival claim invites action
- **WHEN** the claim's agency fields are validated
- **THEN** the claim SHALL encode `kind="invitation"`, `choice="open"`, and `success="unspecified"`
- **AND** the prose SHALL NOT assert a player choice or successful outcome

### Requirement: Study 3 requests SHALL use the fixed scene and model envelope (R15)

The provider-free request builder SHALL render the exact approved scenes and model envelope. The approved three-attempt cap SHALL be bound to `mise-en-scene-study3-20261110`, not a run ID or root, and SHALL remain separate from software readiness and dispatch authorization.

#### Scenario: Request builder preserves scene order and envelope
- **GIVEN** the Study 3 protocol and frozen scene bindings are loaded
- **WHEN** the request builder renders each scene for a fake transport
- **THEN** the captured messages, injected schema, model, provider settings, and generation limits SHALL match the frozen Study 3 envelope and the exact scene order SHALL be preserved
- **AND** the scene order SHALL be `into_the_deepvault:scene:ha003-i02`, `into_the_deepvault:scene:sd005-i03`, then `xhalruuns_masquerade:scene:tsu001-ao02`
- **AND** the model SHALL be `openai/gpt-6-luna` via OpenRouter with `allow_fallbacks=false`, no retries, reruns, tools, redirects, streaming, or continuation, `max_tokens=16384`, and `timeout_seconds=720`
- **AND** no HTTP or provider call SHALL occur

#### Scenario: Cost figures remain estimates
- **GIVEN** sizing is reported from hand-assembled references and the already hash-bound historical rate record
- **WHEN** the preparation packet reports cost
- **THEN** it SHALL distinguish the approximately USD 0.01 expected estimate from the approximately USD 0.03 conservative 16,384-token-envelope estimate, label both ESTIMATE, and record a separate USD 0.05 hard ceiling

#### Scenario: Authorized Overseer cap approval satisfies the owner approval pin
- **GIVEN** the cap is exactly three attempts, one per scene, and is bound to `mise-en-scene-study3-20261110`; the standing-authority ruling `neq-standing-authority-20261110` and cap approval ruling `neq-study3-pre-approved-20261110` are present and match the approved envelope
- **WHEN** the cap approval is checked
- **THEN** the authorized Overseer approval SHALL be accepted as approval for the owner without requiring another owner-only approval
- **AND** a mutable, self-asserted approval JSON SHALL NOT substitute for either ruling pin
- **AND** the approval SHALL NOT by itself authorize software readiness or any generation call

### Requirement: Study 3 references SHALL pass the complete unchanged safety pipeline (R16)

Each Study 3 reference SHALL be hand assembled from its frozen expected inputs and source material, hydrated in memory, and passed through every unchanged downstream safety gate. Canonical inputs SHALL NOT be mutated or persisted. Gate results SHALL distinguish pre-hydration contract rejection from downstream failure.

#### Scenario: Hand-assembled references reach all gates
- **GIVEN** one hand-assembled reference exists for each approved scene and the fake transport captures the exact production request
- **WHEN** provider-free reference regression runs
- **THEN** the run SHALL exercise full hydration and all existing gates without writing canonical inputs or reading model-generated output

#### Scenario: Deterministic reference pass is not a study verdict
- **GIVEN** a hand-assembled reference passes deterministic validation
- **WHEN** preparation status is reported
- **THEN** semantic review, owner ratings, and model capability verdict SHALL remain PENDING
- **AND** software-preparation readiness SHALL remain PENDING unless every R19 gate is complete and approved

#### Scenario: Negative reference mutations cover every unchanged gate
- **GIVEN** provider-free hand-assembled references pass through the Study 3 contract and in-memory hydrator
- **WHEN** a separate semantic mutation targets each existing downstream gate category
- **THEN** mutations SHALL cover schema, fixture/provenance, topology/identity, positional coverage, protected unknowns, source/knowledge boundaries, agency, and guarded markers
- **AND** each mutation SHALL be rejected by its intended gate with a localized deterministic diagnostic
- **AND** the regression report SHALL not attribute pre-hydration contract rejection to a downstream gate

#### Scenario: Hydration preserves canonical fixture identity and provenance
- **GIVEN** a hand-assembled reference is hydrated in memory
- **WHEN** the hydrated fixture is compared with its canonical inputs
- **THEN** canonical facts and provenance, protected unknowns, topology, fixed identities, and mobile identities SHALL match their frozen expected values

#### Scenario: A dependency-blocked gate is explicitly not evaluated
- **GIVEN** a downstream check depends on a value or prerequisite that is invalid or unavailable
- **WHEN** the reference or diagnostic gate chain runs
- **THEN** that dependent check SHALL be reported as `NOT_EVALUATED` with the blocking dependency and reason
- **AND** it SHALL NOT be reported as PASS or terminate as an unhandled crash

### Requirement: Software-preparation readiness SHALL be independently gated (R19)

Study 3 execution SHALL remain blocked until all required software gates and 11 CI checks pass on the exact published SHA and provider-free preflight on that same SHA has zero infrastructure failures. The approved ruling authorizes primary-owned execution after those gates without further per-step approval; post-study semantic review SHALL remain independent.

#### Scenario: Exact-SHA gates permit conditional execution
- **GIVEN** bidirectional parity, collect-all diagnostic coverage, all three reference/full-gate regressions, focused Study 3 tests, the full 196-baseline mise-en-scene and 276-test mapping suites, frozen-file inventories, all 11 CI checks on the exact published DRAFT SHA, and provider-free preflight on that same SHA all pass with zero infrastructure failures
- **WHEN** the primary begins the authorized run
- **THEN** execution SHALL be permitted under `neq-s-study3-runner-revision-20261111` and the pinned cap rulings without another per-step approval
- **AND** the run SHALL remain distinct from semantic review, owner ratings, and model-capability verdict

#### Scenario: Failed, unavailable, or mismatched exact-SHA gate blocks execution
- **GIVEN** a required gate or CI check fails or is unavailable, CI is green only on a different SHA, or exact-SHA provider-free preflight reports an infrastructure failure
- **WHEN** the primary checks run readiness
- **THEN** execution SHALL remain blocked before real ledger initialization, credential access, or HTTP
- **AND** a dependency-blocked check SHALL be `NOT_EVALUATED`, never PASS

#### Scenario: Publication remains draft-only
- **GIVEN** publication is needed to run exact-head CI
- **WHEN** the primary publishes the change
- **THEN** publication to PR127 or a successor DRAFT PR SHALL be permitted
- **AND** the PR SHALL NOT be merged
- **AND** green checks on any other head SHALL NOT satisfy the exact-SHA gate

#### Scenario: The run stops for independent semantic review
- **GIVEN** the primary completes all three attempts or the stop matrix ends the run earlier
- **WHEN** execution evidence is preserved
- **THEN** the primary SHALL stop for independent post-study semantic review
- **AND** the primary SHALL NOT self-score, expose output prose in status reports, or claim a model-capability verdict
- **AND** owner ratings and semantic review SHALL remain PENDING until separately completed

#### Scenario: Preflight does not create a study outcome
- **GIVEN** exact-SHA provider-free preflight passes
- **WHEN** preflight status is reported
- **THEN** it SHALL NOT be reported as a generation result, semantic review, owner rating, or model-capability verdict

### Requirement: Study 3 preparation SHALL remain allocation- and provider-free (R17)

Provider-free Study 3 preparation and tests SHALL make no provider call, credential access, real-ledger initialization, or attempt allocation. Separately authorized execution SHALL use the isolated Study 3 ledger, fixed approved cap, and conditional exact-SHA gate without resetting allocation through run-ID or root changes.

#### Scenario: Preparation has no external side effects
- **GIVEN** the Study 3 preparation or provider-free test suite runs
- **WHEN** network, credential, and real-ledger tripwires are active
- **THEN** the run SHALL make no HTTP/provider call, read no credential, initialize no real ledger, and allocate no attempt

#### Scenario: Missing approval pins or unsafe state fails closed
- **GIVEN** either exact cap-approval ruling pin (`neq-standing-authority-20261110` or `neq-study3-pre-approved-20261110`) is absent or mismatched, the conditional exact-SHA gates have not passed, the fixed cap is exhausted, or the isolated ledger is pending or corrupt
- **WHEN** provider-free dispatch-preflight is exercised
- **THEN** it SHALL refuse before real reservation, credential access, and HTTP, without resetting allocation by changing run ID or root
- **AND** mutable self-asserted approval JSON SHALL NOT substitute for either ruling pin

#### Scenario: Conservative envelope is strictly below the hard ceiling
- **GIVEN** preflight computes the conservative predicted cost for all three approved calls from the already-bound historical rate record
- **WHEN** the total is USD 0.05 or greater or cannot be calculated from valid provenance
- **THEN** it SHALL refuse before real reservation, credential access, and HTTP
- **AND** it SHALL make no additional availability GET

#### Scenario: Preparation tests remain provider-free
- **GIVEN** provider-free tests exercise the Study 3 runner and ledger
- **WHEN** fake transports, socket tripwires, and temporary Study 3 roots are used
- **THEN** tests SHALL not reach the network, read credentials, initialize the real ledger, or allocate a real attempt

### Requirement: Study 2 diagnostic re-gating SHALL collect violations without changing evidence (R20)

Study 3 SHALL provide collect-all diagnostics that operate only on copies of the three frozen Study 2 deltas outside the evidence tree and label outputs `DIAGNOSTIC_NOT_STUDY_RESULT`. Diagnostics SHALL preserve original evidence and copies, use project-relative `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3-prep/`, and not claim three examples prove no hidden rule exists.

#### Scenario: Diagnostic mode reports independent violations together
- **GIVEN** a copied Study 2 delta has multiple independently evaluable rule violations
- **WHEN** collect-all diagnostic mode runs
- **THEN** it SHALL report every independently evaluable violation in that copy rather than stopping at the first
- **AND** each finding SHALL identify its rule-map entry and request/schema/canonical-input declaration or host-integrity classification

#### Scenario: Dependent diagnostic checks are not falsely passed
- **GIVEN** a diagnostic check requires an invalid or unavailable prerequisite
- **WHEN** collect-all mode evaluates the copy
- **THEN** that check SHALL be `NOT_EVALUATED` with its blocking dependency and reason, while other independent checks continue
- **AND** no dependency-blocked check SHALL be marked PASS or end in an unhandled crash

#### Scenario: Diagnostic copies and study outcomes remain immutable
- **GIVEN** the three Study 2 deltas are copied for diagnostic re-gating
- **WHEN** collect-all mode produces its report
- **THEN** source evidence and copy bytes/values/prose SHALL remain unchanged
- **AND** outputs SHALL be labeled `DIAGNOSTIC_NOT_STUDY_RESULT` and SHALL NOT change Study 2's frozen verdict or be represented as a Study 3 result

### Requirement: Study 3 execution SHALL use an isolated durable attempt ledger (R21)

Execution SHALL reserve each scene once in a durable ledger confined to the Study 3 root before credential access or dispatch. Ledger state SHALL bind the fixed Study 3 identity, exact scene order, request hash, attempt outcome, and actual-cost state; unsafe, pending, duplicate, or corrupt state SHALL fail closed without reset.

#### Scenario: Reservation is durable before dispatch
- **GIVEN** exact-SHA pre-call gates pass and the primary requests the next approved scene
- **WHEN** the runner reaches credential lookup or the transport boundary
- **THEN** one durable reservation bound to the fixed identity, scene/order, request hash, and budget reservation SHALL already exist
- **AND** the reservation SHALL be flushed before credential access or HTTP

#### Scenario: Paths remain confined to the Study 3 root
- **GIVEN** a ledger, response, or result path contains traversal, resolves outside the Study 3 root, or traverses a symlink
- **WHEN** reservation or evidence creation is attempted
- **THEN** the operation SHALL fail before any outside-root write or dispatch

#### Scenario: Duplicate, concurrent, or out-of-order reservation is refused
- **GIVEN** a scene already has a reservation, another process concurrently requests the same scene, or the next scene is not the next fixed scene
- **WHEN** a reservation is requested
- **THEN** at most one reservation SHALL be accepted and no duplicate or out-of-order dispatch SHALL occur

#### Scenario: Restarted pending or corrupt ledger is not replayed
- **GIVEN** a restart finds a pending reservation, malformed record, invalid hash chain, changed identity, or duplicate ledger/result artifact
- **WHEN** the runner reloads allocation state
- **THEN** it SHALL refuse dispatch and SHALL NOT reset the cap, retry the reservation, or create a fresh ledger under another run ID/root

### Requirement: Study 3 execution SHALL reuse one-shot transport with the fixed envelope (R22)

The primary runner SHALL dispatch only the three fixed scenes in order through the existing reservation-gated one-shot OpenRouter transport, using the exact approved Study 3 envelope and no ancillary provider lookup.

#### Scenario: One reserved dispatch uses the exact envelope
- **GIVEN** a durable reservation exists for the next approved scene
- **WHEN** one transport dispatch occurs
- **THEN** it SHALL use OpenRouter model `openai/gpt-6-luna`, `allow_fallbacks=false`, `max_tokens=16384`, and a 720-second timeout
- **AND** it SHALL issue exactly one POST with no retry, rerun, redirect, streaming, continuation, or tools
- **AND** provider credentials SHALL be read only after reservation

#### Scenario: No additional availability lookup occurs
- **GIVEN** the existing model availability evidence and exact frozen request pins are present
- **WHEN** preflight or the three-scene execution runs
- **THEN** it SHALL NOT make another models-list GET or any other ancillary provider request

#### Scenario: Identity, transport, and HTTP status failures stop remaining attempts
- **GIVEN** a durable reservation exists and the attempt encounters a returned provider identity failure, transport failure/timeout, or non-200 response
- **WHEN** the outcome is recorded
- **THEN** the reserved attempt SHALL remain consumed and the run SHALL stop with later scene reservations unspent

#### Scenario: HTTP 200 with invalid content consumes only its scene
- **GIVEN** a response has HTTP 200 but fails the Study 3 output contract
- **WHEN** its outcome and actual cost are recorded
- **THEN** that scene's attempt SHALL be consumed and the next scene MAY proceed only if actual cost is reconciled and the remaining budget is safe
- **AND** no retry, rerun, or fallback SHALL occur

### Requirement: Study 3 actual cost SHALL be reconciled fail-closed (R23)

Historical rate-derived figures SHALL remain labeled estimates, while dispatch SHALL maintain a separate USD 0.05 ceiling and require a valid actual-cost receipt before any subsequent scene can be dispatched.

#### Scenario: Historical costs remain estimates
- **GIVEN** the existing hash-bound historical rate record is used for sizing
- **WHEN** the expected and conservative amounts are reported
- **THEN** USD 0.0125671 and USD 0.0324461 SHALL be labeled `ESTIMATE`
- **AND** neither estimate SHALL be represented as actual spend or as the hard ceiling

#### Scenario: Budget refusal happens before dispatch
- **GIVEN** the conservative remaining envelope is USD 0.05 or greater or cannot be calculated from valid historical provenance
- **WHEN** the next attempt is considered
- **THEN** the runner SHALL refuse before credentials and HTTP
- **AND** it SHALL NOT fetch availability or replace the historical rate record

#### Scenario: Missing or inconsistent actual cost blocks later dispatch
- **GIVEN** a completed HTTP response has missing, pending, malformed, or inconsistent actual-cost data
- **WHEN** the ledger reconciles the attempt
- **THEN** it SHALL record accounting as unresolved and stop further dispatch without another network request

#### Scenario: Actual cost is bound to the reserved attempt
- **GIVEN** an actual-cost receipt is available for a response
- **WHEN** the ledger records the result
- **THEN** the cost SHALL be bound to that reservation and included in cumulative Study 3 spend
- **AND** no later attempt SHALL be dispatched when cumulative actual cost plus the conservative remaining envelope reaches or exceeds USD 0.05

### Requirement: Study 3 outputs SHALL remain private pending semantic review (R24)

Raw provider output SHALL remain under the private Study 3 evidence root until independent post-study semantic review. Logs and status records SHALL exclude credentials, prompt text, and response prose; semantic review and owner ratings SHALL remain pending until separately performed.

#### Scenario: Raw output is stored privately
- **GIVEN** the one-shot transport returns a bounded provider response
- **WHEN** the runner persists response evidence
- **THEN** the raw response SHALL be stored only under the Study 3 root with restrictive directory/file permissions
- **AND** ledger records SHALL contain only safe metadata, hashes, and accounting receipts

#### Scenario: Status and error paths do not disclose secrets or output prose
- **GIVEN** a credential or provider response contains sensitive text or an error occurs
- **WHEN** status, logs, exceptions, or cost records are written
- **THEN** they SHALL contain no credential, prompt text, or response prose
- **AND** a credential echo SHALL be redacted or the response rejected safely

#### Scenario: Execution does not self-review outputs
- **GIVEN** the primary has completed the run or an earlier stop boundary
- **WHEN** the execution handoff is produced
- **THEN** it SHALL report only metadata and actual receipts/costs, leave semantic review and owner ratings pending, and stop for the independent reviewer
