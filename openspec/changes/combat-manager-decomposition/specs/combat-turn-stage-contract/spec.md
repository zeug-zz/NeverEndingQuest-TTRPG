# Spec Delta

## Purpose

Defines the named combat-turn boundaries and decision handoff needed to make the runtime understandable and provide a stable target for the next router migration.

## ADDED Requirements

### Requirement: Combat turn exposes nine responsibility stages without reordering legacy execution

The combat runtime SHALL expose nine named responsibility stages: input/phase gate; fast commands; PC-action decision seam; context/prompt; provider retry; validation; apply/commit; phase transitions; narration/output. The names and logical handoffs SHALL NOT change the validated legacy physical execution, mutation, persistence, or publication order.

#### Scenario: Normal validated-response path preserves legacy call order
- **WHEN** an input passes the phase gate and is not handled by a deterministic fast command
- **THEN** the runtime SHALL retain this order: round metadata/phase preparation and save/compress; print narration and flush; immediate encounter actions and queued character updates; post-batch phase and turn-queue bookkeeping; consolidated character updates
- **AND** the runtime SHALL retain existing branch, retry, early-return, break, and continue outcomes
- **AND** each named stage SHALL execute its work at the existing call point, allowing pre- or post-substeps without moving work across those points

#### Scenario: Stage names do not impose a synthetic final narration call
- **WHEN** narration/output is extracted as a named responsibility
- **THEN** real narration and output SHALL remain at the legacy publication point
- **AND** the runtime SHALL NOT add an empty final-narration shim or move publication after consolidated character updates

#### Scenario: Fast command remains at its legacy call point before provider prompt assembly
- **WHEN** a supported fast command is handled deterministically
- **THEN** its existing command result SHALL be returned without entering provider retry
- **AND** the stage boundary SHALL preserve the command's current state and output effects

### Requirement: PC-action decision seam preserves decision outcomes

The PC-action decision seam SHALL distinguish `declined` from `unavailable`, and both outcomes SHALL continue through the current LLM path without changing provider-call policy.

#### Scenario: Decision declines a PC action
- **WHEN** the decision seam returns `declined`
- **THEN** telemetry or stage result SHALL preserve that status distinctly
- **AND** the existing LLM prompt path SHALL continue

#### Scenario: Decision mechanism is unavailable
- **WHEN** the decision seam returns `unavailable`
- **THEN** telemetry or stage result SHALL preserve that status distinctly from `declined`
- **AND** the existing LLM prompt path SHALL continue

#### Scenario: Decision result avoids no authorized provider call
- **WHEN** either seam outcome is produced in this decomposition
- **THEN** the decomposition SHALL NOT add a provider call, remove an existing call, or change an existing provider-call budget
