# toolkit-adaptation-rights-basis-contract Specification

## Purpose
Defines the exact contract for preserving Python-owned rights-basis metadata across adaptation authoring without allowing provider paraphrase or policy relabeling.
## Requirements
### Requirement: Python-owned rights basis is an exact authoring identity

The adaptation author contract MUST identify `rights_basis` as a Python-provided value, and a build-ready dossier MUST echo that value character-for-character. The provider MUST NOT paraphrase, translate, replace, or infer the value from source prose.

#### Scenario: User-authored upload uses the canonical basis

- **WHEN** Python classifies an eligible upload as `user_authored` with `rights_basis` equal to `user_authored_uploaded_adventure`
- **THEN** the author request MUST require that exact value in the dossier
- **AND** a dossier containing that exact value MUST preserve it through the adaptation handoff

#### Scenario: Text description uses the canonical basis

- **WHEN** Python classifies an eligible text description as `user_authored` with its Python-owned rights basis
- **THEN** the author request MUST require that exact value in the dossier
- **AND** the value MUST remain unchanged in the persisted handoff and provenance metadata

### Requirement: Rights-basis mismatch fails closed before publication

If a provider dossier changes the Python-owned `rights_basis`, the runtime MUST reject the dossier as a bounded rights/provenance contract failure before ModuleBuilder execution or publication. The failure MUST be non-retryable under the semantic revision budget and MUST NOT silently fall back to the legacy route.

#### Scenario: Provider paraphrases the rights basis

- **WHEN** Python expects a canonical rights-basis token and the provider returns a human-readable paraphrase
- **THEN** the adaptation attempt MUST be marked blocked with reason code `rights_or_provenance_mismatch`
- **AND** the failure diagnostics MUST identify `rights_basis` without retaining the raw provider response
- **AND** no module, registry, or campaign publication side effect MAY occur

#### Scenario: Provider preserves the rights basis

- **WHEN** the provider returns the exact Python-owned rights basis along with matching source identity and review metadata
- **THEN** rights-basis validation MUST pass
- **AND** subsequent schema, readiness, staging, and publication gates MUST remain authoritative

### Requirement: Rights policy remains Python-authoritative

The adaptation runtime MUST continue to treat Python as the source of truth for `source_hash`, source identity, `rights_class`, `rights_basis`, `rights_review_required`, and `rights_review_status`. A provider response MUST NOT relabel an input, clear a required review state, or convert a restricted input into a build-ready input.

#### Scenario: Provider attempts a rights relabel

- **WHEN** a provider changes `rights_class` or review metadata while returning an otherwise valid dossier
- **THEN** Python MUST reject the dossier as a rights/provenance failure
- **AND** the attempt MUST remain blocked without semantic revision or legacy fallback

#### Scenario: Restricted input remains review-gated

- **WHEN** Python marks an input as restricted or review-pending
- **THEN** provider output MUST NOT make it build-ready by changing `rights_basis`, `rights_class`, or review fields
- **AND** publication MUST remain unattempted until the existing Python-owned review requirements are satisfied
### Requirement: Public diagnostics remain bounded

Rights/provenance failures exposed to Toolkit status surfaces MUST contain only bounded allowlisted fields, including the failure code, safe failure class, retry status, publication status, and the affected metadata field when available. They MUST NOT expose raw source text, full prompts, provider response bodies, credentials, or authorization data.

#### Scenario: Blocked authoring status is displayed

- **WHEN** a rights-basis mismatch reaches a Toolkit status surface
- **THEN** the user-facing status MAY identify `rights_or_provenance_mismatch` and `rights_basis`
- **AND** the payload MUST report `raw_provider_payload_exposed` as false
- **AND** the payload MUST show publication as not attempted or incomplete when no publication transaction ran
