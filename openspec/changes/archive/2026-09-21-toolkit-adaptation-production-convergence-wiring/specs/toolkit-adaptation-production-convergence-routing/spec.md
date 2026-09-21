## Purpose

Routes eligible enabled Toolkit adaptation builds through the completed bounded convergence contract so production builds can reach final gates without silently falling back to legacy generation.

## ADDED Requirements

### Requirement: Enabled adaptation builds SHALL have a production convergence boundary

An eligible build selected for `llm_adaptation` SHALL invoke a production convergence boundary after the staged build succeeds and before final readiness and publication evaluation. The boundary SHALL carry the current attempt, revision, source identity, and project-relative staging identity.

#### Scenario: Deterministic staging has no repairable blocker

- **WHEN** an enabled adaptation build reaches convergence and deterministic checks identify no repairable proposal request
- **THEN** the convergence boundary SHALL return a bounded success without a provider call
- **AND** the build SHALL continue to the existing final gate set

#### Scenario: Deterministic staging has a repairable blocker

- **WHEN** an enabled adaptation build reaches convergence with a genuinely repairable bounded blocker
- **THEN** the boundary SHALL send only the bounded request context allowed by the convergence contract to the configured provider
- **AND** the provider response SHALL remain a proposal until Python validation accepts it

### Requirement: Provider proposals and failures SHALL remain staging-safe

The production boundary SHALL accept only a Python-validated, allowlisted convergence operation for the current staging identity. Provider timeout, quota, dependency, unavailable, malformed, rejected, or invalid proposal outcomes SHALL produce bounded diagnostics and SHALL leave the current staging revision unchanged.

#### Scenario: Provider returns an invalid proposal

- **WHEN** the provider proposes an unknown operation, stale identity, unsupported target, invalid source reference, low-confidence result, topology contradiction, or arbitrary field
- **THEN** Python SHALL reject the proposal with a bounded failure classification
- **AND** the adaptation build SHALL remain blocked
- **AND** no live module, registry, campaign, or legacy fallback write SHALL occur

#### Scenario: Provider is unavailable

- **WHEN** the configured provider times out, exceeds quota, cannot initialize, or returns unavailable infrastructure
- **THEN** the attempt SHALL persist the bounded provider failure class and current staging identity
- **AND** the current staging revision SHALL remain available for an explicit eligible retry
- **AND** the selected adaptation route SHALL not silently downgrade to legacy generation

### Requirement: Legacy routing SHALL remain isolated

Missing, invalid, or `False` `ENABLE_LLM_ADAPTATION` values and ineligible inputs SHALL retain their existing legacy routes and SHALL not require adaptation convergence callbacks, staging reports, or provider metadata. A route already selected as adaptation SHALL fail closed rather than silently downgrade.

#### Scenario: Adaptation is disabled

- **WHEN** an eligible upload or text-description build runs with `ENABLE_LLM_ADAPTATION=False`, missing, or invalid
- **THEN** the build SHALL use its existing legacy route
- **AND** no adaptation convergence callback, proposal, or staging artifact SHALL be required

#### Scenario: Selected adaptation fails

- **WHEN** an eligible build has selected `llm_adaptation` and authoring, convergence, validation, readiness, or publication fails
- **THEN** the job SHALL emit a bounded adaptation failure
- **AND** it SHALL not invoke the legacy accurate-ingest or direct ModuleBuilder fallback

### Requirement: Convergence reporting SHALL preserve current identity

Every production convergence result and downstream gate report consumed for publication SHALL preserve one matching attempt ID, attempt number, revision number, source hash, and staging-relative module path. Stale or mismatched reports SHALL block publication.

#### Scenario: Reports match the current revision

- **WHEN** convergence and all final gates consume reports with the same current identity
- **THEN** the build MAY proceed to the existing publication boundary if all required gate statuses pass

#### Scenario: A stale report is detected

- **WHEN** any consumed convergence, validation, readiness, semantic, gameplay, or publication report identifies another revision or source hash
- **THEN** the build SHALL remain non-publishable with a bounded stale-identity diagnostic
- **AND** no live state SHALL be promoted
