## Purpose

Defines reliable GPT-5-family adaptation author requests, strict dossier output, and safe diagnostics for model refusals without weakening Python validation or rights policy.

## ADDED Requirements

### Requirement: Author output is strict structured data

The adaptation author request SHALL require one bounded structured dossier that satisfies the completed `toolkit_adaptation_dossier.v1` contract, and Python SHALL remain the final schema and cross-field validator.

#### Scenario: Ready dossier response

- **WHEN** the provider returns a structured dossier with matching source identity, rights metadata, required playable seeds, and `status: ready`
- **THEN** Python SHALL parse and validate it as build-ready
- **AND** SHALL not treat provider schema compliance as publication success

#### Scenario: Invalid structured response

- **WHEN** the provider returns malformed JSON, unsupported fields, invalid ASCII/bounds, or a dossier that fails the schema
- **THEN** the runtime SHALL return an invalid-model-response outcome
- **AND** SHALL stop before staging publication work

### Requirement: Refusal classes remain distinguishable

The runtime SHALL distinguish provider/API refusal, author-policy refusal, provider transport failure, quota/timeout failure, parameter-resolution failure, and dossier validation failure in bounded attempt diagnostics.

#### Scenario: Author-policy refusal

- **WHEN** the provider returns a valid dossier with `status: refused`, such as a rights-review refusal
- **THEN** the runtime SHALL preserve the refusal outcome and bounded dossier warnings/reason code
- **AND** SHALL not convert it into a build-ready dossier

#### Scenario: API refusal

- **WHEN** the provider response uses the API refusal channel instead of returning dossier JSON
- **THEN** the runtime SHALL record a provider-refusal outcome without retaining unbounded refusal text
- **AND** SHALL not consume the semantic revision budget

#### Scenario: Provider infrastructure failure

- **WHEN** the provider call fails due to quota, timeout, dependency, connection, or service availability
- **THEN** the runtime SHALL report the corresponding infrastructure failure class
- **AND** SHALL preserve the attempt for operator diagnostics without semantic revision

### Requirement: Provider refusal diagnostics do not leak secrets or raw source

Provider/model diagnostics exposed to reports or job polling SHALL be bounded and allowlisted; they SHALL NOT include credentials, full prompts, unbounded source text, or arbitrary provider response bodies.

#### Scenario: Safe refusal report

- **WHEN** an adaptation author request is refused
- **THEN** the report SHALL include bounded provider/model identifiers, attempt identity, failure class, and a safe reason category when available
- **AND** SHALL omit credentials, raw prompt content, and unbounded refusal text

### Requirement: GPT-5 request parameters remain compatible

The author request SHALL use the repository's GPT-5-family parameter resolver and SHALL omit unsupported legacy sampling controls for direct OpenAI requests.

#### Scenario: Direct GPT-5-family request

- **WHEN** adaptation authoring uses the configured direct OpenAI GPT-5-family model
- **THEN** the request SHALL use the resolved reasoning/verbosity profile and structured-output contract
- **AND** SHALL not add unsupported legacy sampling parameters
