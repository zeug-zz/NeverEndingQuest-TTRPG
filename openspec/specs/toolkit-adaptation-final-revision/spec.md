# toolkit-adaptation-final-revision Specification

## Purpose
Defines the bounded LLM semantic audit that revises a failed adaptation dossier and causes a fresh ModuleBuilder build without allowing arbitrary model patches to live module files.

## Requirements

### Requirement: Build failures are classified before revision

The adaptation pipeline MUST distinguish infrastructure failures, mechanical structural failures, semantic adaptation failures, rights or policy failures, and publication failures before deciding whether to invoke the final semantic auditor.

#### Scenario: Provider failure

- **WHEN** a provider call fails because of quota, timeout, unsupported parameters, or client initialization
- **THEN** the pipeline records an infrastructure failure and does not spend semantic revision budget

#### Scenario: Semantic failure

- **WHEN** the generated module fails a content or semantic gate while provider and file operations are healthy
- **THEN** the pipeline creates a failure packet for the final semantic auditor

### Requirement: Final auditor returns a revised adaptation contract

The final semantic auditor MUST receive compact failure diagnostics and MUST return a strict revision response containing `revise`, `refuse`, or `failed` status and a revised dossier or rebuild directive.

#### Scenario: Accepted revision

- **WHEN** the auditor returns a valid revision response
- **THEN** Python validates the response contract and makes it available for a fresh ModuleBuilder attempt

#### Scenario: Unsafe revision

- **WHEN** the auditor returns malformed JSON, arbitrary file targets, unsupported status, or an unsafe direct-write instruction
- **THEN** the revision is rejected and the adaptation remains unpublished

### Requirement: Semantic revision is bounded and fresh

The adaptation pipeline MUST enforce a hard semantic revision budget and MUST build a revision in a fresh staging or backup-safe target.

#### Scenario: Revision passes

- **WHEN** a revised dossier produces a module that passes all publication gates
- **THEN** the revised attempt becomes the candidate for publication and records the revision number

#### Scenario: Revision budget exhausted

- **WHEN** the maximum revision budget is reached without a passing candidate
- **THEN** the job ends in an explicit failed or blocked state and no registry entry is created

### Requirement: Final revision never mutates arbitrary runtime state

The LLM revision path MUST NOT write directly to world registry, campaign state, live mechanical state, source uploads, or arbitrary files outside the controlled build target.

#### Scenario: Direct runtime write request

- **WHEN** an auditor response requests a write to `world_registry.json`, `campaign.json`, or runtime state
- **THEN** Python rejects the response before any file mutation

#### Scenario: Fresh module rebuild

- **WHEN** an auditor response is accepted
- **THEN** ModuleBuilder creates the candidate from the revised dossier through the controlled build path
