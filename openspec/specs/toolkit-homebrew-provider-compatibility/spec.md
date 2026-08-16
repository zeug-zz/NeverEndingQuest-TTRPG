## Purpose

Ensures Homebrew normalization, ModuleBuilder generation, and Markdown enrichment fail with truthful provider diagnostics instead of producing misleading placeholder success artifacts.

## Requirements

### Requirement: Priority Homebrew calls use the shared compatibility boundary

Priority Homebrew and ModuleBuilder calls MUST use the shared provider-aware request parameter contract before invoking the provider.

#### Scenario: Homebrew normalization on GPT-5.6 Luna

- **WHEN** a readable Homebrew source enters normalization with GPT-5.6 Luna configured
- **THEN** the normalizer sends a supported request shape rather than passing direct legacy sampling parameters

#### Scenario: ModuleBuilder generation on GPT-5.6 Luna

- **WHEN** ModuleBuilder invokes a generator with GPT-5.6 Luna configured
- **THEN** the generator sends the supported GPT-5 request profile

### Requirement: Provider request failures are stage-specific

A provider rejection, quota error, timeout, or client initialization failure MUST be recorded with the current build stage and MUST NOT be represented as a successful normalized packet or completed module.

#### Scenario: Unsupported parameter rejection

- **WHEN** the provider rejects a build request because of an unsupported parameter
- **THEN** the stage returns an explicit provider compatibility failure and no false success artifact is promoted

#### Scenario: Provider outage

- **WHEN** the provider is unavailable during a build call
- **THEN** the stage returns a retryable or terminal provider failure according to existing provider policy and preserves diagnostic context

### Requirement: Provider compatibility is provider-free testable

The Homebrew compatibility contract MUST be testable with a mock client that captures final request kwargs without making a live provider call.

#### Scenario: Captured GPT-5 kwargs

- **WHEN** a provider-free test invokes a migrated build call with a GPT-5 model
- **THEN** captured kwargs contain the expected reasoning profile and no unsupported legacy sampling fields

#### Scenario: Captured OpenRouter kwargs

- **WHEN** a provider-free test invokes the same task under OpenRouter configuration
- **THEN** captured kwargs retain the expected OpenRouter-specific request fields
