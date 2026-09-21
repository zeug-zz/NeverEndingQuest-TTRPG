## Purpose

Ensure `llm_adaptation` encounter adversary labels that differ only by bounded quantity or ordinary plural wording converge to one Python-owned canonical monster identity before reuse, generation, verification, and encounter binding.

## ADDED Requirements

### Requirement: Adaptation Identity Variants Are Bounded And Deterministic

The adaptation monster guardrail MUST derive a bounded ordered identity key from each dossier adversary using raw normalization, an explicit leading quantity fold when present, and an ordinary terminal plural fold when unambiguous. It MUST preserve the original source label separately and MUST NOT infer identity from arbitrary descriptive prose.

#### Scenario: Plural adversary matches singular canonical identity

- **WHEN** a dossier adversary is `Memory-thief impersonations` and the canonical identity is `Memory-thief impersonation`
- **THEN** the guardrail MUST use one canonical identity for materialization
- **AND** the raw plural label MUST remain available in bounded diagnostics or provenance

#### Scenario: Quantity-qualified adversary matches canonical identity

- **WHEN** a dossier adversary is `Two slime spawn` and the canonical identity is `Slime spawn`
- **THEN** the quantity prefix MUST NOT create a second monster identity
- **AND** the encounter quantity remains source data rather than part of the filename identity

#### Scenario: Broad creature wording is not silently folded

- **WHEN** an adversary contains a custom or broad term such as `Guardian`, `Ooze`, or a unique named creature
- **THEN** the guardrail MUST NOT classify or replace it solely because of that term
- **AND** unresolved or provider-substitution behavior remains fail-closed

### Requirement: Materialization Is Exact-First And Duplicate-Free

Adaptation materialization MUST try exact raw reusable artifacts before folded identity variants, then copy or generate at one canonical staging path. A successful resolution MUST NOT create duplicate plural and singular artifacts for one identity.

#### Scenario: Singular generated payload resolves qualified source labels

- **WHEN** generation is allowed for `Memory-thief impersonations` or `Two slime spawn`
- **THEN** Python MUST pass the selected canonical identity to the staging-only builder
- **AND** a schema-sufficient singular payload MUST resolve the reference
- **AND** the plural or quantity-qualified artifact MUST NOT remain as a duplicate

#### Scenario: Exact authored artifact remains authoritative

- **WHEN** an exact raw reusable artifact is schema-sufficient
- **THEN** it MUST be reused before folded lookup or generation
- **AND** the report MUST identify the exact artifact as reused

### Requirement: Identity Verification Remains Fail-Closed

The guardrail MUST verify generated and reused payload names against the selected canonical identity variants. It MUST reject a schema-sufficient payload that substitutes a different identity.

#### Scenario: Provider substitutes another monster

- **WHEN** Python requests `Memory-thief impersonation` and the provider returns `Substituted Beast`
- **THEN** the artifact MUST be rejected and removed from the active staging target
- **AND** the reference MUST remain unresolved with a concrete diagnostic

### Requirement: Encounter Binding Uses The Same Identity Key

Encounter context lookup and binding MUST use the same bounded identity semantics as materialization. A seed containing a folded alias MUST bind to its resolved canonical artifact.

#### Scenario: Amphail encounter seeds bind after convergence

- **WHEN** the dossier contains singular, plural, and quantity-qualified aliases for the same approved identities
- **THEN** all four valid Amphail encounter seeds MUST be reported as bound when their canonical artifacts resolve
- **AND** no alias-only seed may remain unresolved solely because of wording variation

### Requirement: Legacy Behavior Is Isolated

The identity convergence behavior MUST apply only to adaptation materialization and MUST NOT alter non-adaptation ModuleBuilder or generic closure behavior.

#### Scenario: Legacy build executes

- **WHEN** a non-adaptation module build invokes existing monster closure
- **THEN** the new adaptation identity helper MUST NOT change its resolution or output behavior
