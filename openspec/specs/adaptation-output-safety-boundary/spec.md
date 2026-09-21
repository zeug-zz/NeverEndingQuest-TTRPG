# adaptation-output-safety-boundary Specification

## Purpose
Ensure adaptation stdout, stderr, GUI chat, progress payloads, and logger emissions expose only bounded safe status information.

## Requirements

### Requirement: Adaptation output is bounded and phase-oriented

While an adaptation scope is active, emitted output MUST be limited to bounded ASCII-safe phase, status, count, attempt/revision, and failure-code fields. Raw source, full prompts, source-context blocks, full provider responses, request bodies, credentials, authorization headers, and absolute filesystem paths MUST NOT be emitted.

#### Scenario: Adaptation progress event

- **WHEN** an adaptation stage reports progress
- **THEN** the event MUST contain a recognized stage/status/code and bounded counts or message text
- **AND** it MUST not contain source, prompt, response, credential, or path payloads

### Requirement: Unsafe captured lines are sanitized before emission

Adaptation stdout/stderr capture MUST sanitize or suppress sensitive lines before forwarding them to original streams, GUI chat, progress callbacks, or log handlers.

#### Scenario: Sentinel source and provider response

- **WHEN** a builder or provider emits sentinel source, prompt, response, token, or authorization text
- **THEN** none of those sentinel values may appear in adaptation stdout, stderr, GUI/progress payloads, or persisted diagnostics
- **AND** a bounded safe stage/code may remain visible

### Requirement: Hard failures remain visible

The output boundary MUST preserve a bounded meaningful stage and failure code for every terminal adaptation failure even when verbose output is suppressed.

#### Scenario: Monster closure failure

- **WHEN** adaptation stops with `monster_closure_unresolved`
- **THEN** the output and job envelope MUST retain that code and its bounded stage
- **AND** raw diagnostic tails MUST remain hidden
