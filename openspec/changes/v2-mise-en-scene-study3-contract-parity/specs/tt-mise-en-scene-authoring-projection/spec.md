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

Software-preparation readiness SHALL be READY only when every required software gate passes and the Overseer approves the evidence. Missing, failed, or dependency-blocked evidence SHALL NOT establish READY. Readiness SHALL remain separate from study outcomes and SHALL NOT by itself authorize dispatch.

#### Scenario: All software gates and exact-head review permit readiness
- **GIVEN** bidirectional request/validator parity, collect-all diagnostic coverage with every independently evaluable finding mapped, all three reference/full-gate regressions, focused Study 3 and full 196-baseline mise-en-scene and 276-test mapping suites, and complete frozen-file hash inventories all pass
- **AND** all 11 required CI checks pass on the exact new head of the authorized DRAFT PR127 or successor DRAFT PR
- **AND** the Overseer approves the software-preparation evidence
- **WHEN** software-preparation status is reported
- **THEN** software-preparation readiness MAY be READY
- **AND** semantic review, owner ratings, and model-capability verdict MAY remain PENDING independently
- **AND** no generation or attempt allocation SHALL occur

#### Scenario: Exact-head packet stops at software-preparation review
- **GIVEN** the implementation packet is complete and all 11 required CI checks pass on the exact newly published DRAFT head
- **WHEN** the packet is submitted for review
- **THEN** work SHALL stop for Overseer software-preparation review before any actual generation call
- **AND** no test result, readiness status, or call authorization SHALL be inferred from planning approval or a green CI result on a different head

#### Scenario: Authorized publication remains draft-only
- **GIVEN** Git publication is needed for exact-new-head CI
- **WHEN** the change is published
- **THEN** commit/push to PR127 or a successor DRAFT PR SHALL be permitted
- **AND** the PR SHALL NOT be merged
- **AND** the packet SHALL stop for Overseer software-preparation review after all 11 exact-head checks and required evidence are ready

#### Scenario: Missing gate, failed gate, or old-head CI cannot establish readiness
- **GIVEN** any required software gate or Overseer review is missing, a required gate fails, or CI is green only for a different/old head
- **WHEN** software-preparation status is reported
- **THEN** readiness SHALL be PENDING for missing evidence or BLOCKED for a failed gate, never READY
- **AND** a dependency-blocked check SHALL be `NOT_EVALUATED`, never PASS
- **AND** old-head CI SHALL NOT count as exact-new-head evidence
- **AND** semantic review, owner ratings, and model-capability verdict SHALL remain separate

### Requirement: Study 3 preparation SHALL remain allocation- and provider-free (R17)

Study 3 preparation SHALL be provider-, credential-, real-ledger-, and allocation-free. Any future dispatch SHALL honor the fixed approved cap, require exact approval and post-review authorization, and SHALL NOT reset the cap through run-ID or root changes.

#### Scenario: Preparation has no external side effects
- **GIVEN** the Study 3 preparation or provider-free test suite runs
- **WHEN** network, credential, or real-ledger tripwires are active
- **THEN** the run SHALL make no HTTP/provider call, read no credential, initialize no real ledger, and allocate no attempt

#### Scenario: Missing approval or unsafe allocation state fails closed
- **GIVEN** either exact cap-approval ruling pin (`neq-standing-authority-20261110` or `neq-study3-pre-approved-20261110`), Overseer post-review READY and dispatch authorization, or a safe allocation state is absent; the fixed cap is exhausted; or a synthetic ledger state is pending or corrupt
- **WHEN** a provider-free dispatch-preflight test is exercised
- **THEN** it SHALL refuse before reservation, credential access, and HTTP, without resetting the cap by changing run ID or root
- **AND** a mutable, self-asserted approval JSON SHALL NOT substitute for either ruling pin

#### Scenario: Conservative future preflight remains below the hard ceiling
- **GIVEN** a future dispatch preflight computes a conservative predicted cost for all three approved calls
- **WHEN** that total is USD 0.05 or greater, or cannot be calculated from valid rate provenance
- **THEN** it SHALL refuse before reservation, credential access, and HTTP
- **AND** it SHALL stop safely if subsequent actual cost accounting is missing, pending, or inconsistent

#### Scenario: Future transport failures preserve the stop boundary
- **GIVEN** a separately authorized future attempt receives an identity/transport failure or non-200 response, or receives HTTP 200 with contract-failing content
- **WHEN** the attempt outcome is classified
- **THEN** identity/transport failure and non-200 SHALL stop the study with remaining attempts unspent, while HTTP 200 contract failure SHALL consume that scene's attempt and permit the next scene without retry, rerun, or fallback

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
