## Purpose

Prevent builder, generator, file-operation, and subprocess diagnostics from leaking raw source, prompts, responses, or lock paths during adaptation while preserving safe legacy diagnostics.

## ADDED Requirements

### Requirement: Generator output is safe in adaptation scope

During adaptation, ModuleBuilder, ModuleGenerator, AreaGenerator, location/plot generators, and monster-builder subprocesses MUST NOT print or log full concepts, prompts, source-context blocks, provider responses, request payloads, or raw exception bodies.

#### Scenario: Verbose generator sentinel

- **WHEN** a generator receives or returns a sentinel source/prompt/provider response
- **THEN** the sentinel MUST be absent from adaptation stdout/stderr and persisted tails
- **AND** bounded stage/code telemetry MAY remain

### Requirement: File-operation diagnostics do not expose lock paths

Adaptation file locking MUST NOT print or persist absolute lock paths, lock filenames, or unbounded lock/debug records.

#### Scenario: Locked artifact write

- **WHEN** adaptation writes a staged JSON artifact under a lock
- **THEN** output MAY report a bounded file-operation code or count
- **AND** the lock path MUST not appear in stdout, stderr, GUI/progress, or diagnostics

### Requirement: Legacy diagnostics remain compatible

Raw unsafe output suppression MUST be scoped to adaptation or to the specific sensitive payload. Meaningful non-adaptation CLI diagnostics that do not contain sensitive content MUST remain available.

#### Scenario: Legacy builder command

- **WHEN** a non-adaptation CLI builder runs
- **THEN** its existing safe diagnostic behavior MUST remain available
- **AND** adaptation-only progress fields MUST not be required
