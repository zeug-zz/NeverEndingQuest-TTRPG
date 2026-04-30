# Toolkit MMG Final Media Authority

## Purpose

Ensure Module Builder sidebar media-generator handoff state is governed by Module Media Generator's final module-local media audit rather than stale persisted publishability media-debt reports.

## ADDED Requirements

### Requirement: MMG completion MUST persist a final media authority report

Module Media Generator completion MUST persist a versioned final media report for the module that records whether required module-local media assets are present.

#### Scenario: Final report after generation

- **GIVEN** Module Media Generator completes for `The_Hidden_City_of_Numillian`
- **WHEN** the generation workflow reaches its final audit step
- **THEN** it MUST write `modules/The_Hidden_City_of_Numillian/module_media_generator_report.json`
- **AND** the report MUST include a contract version, source, authoritative flag, status, required asset list, missing asset list, and missing count.

### Requirement: Static fallback media MUST NOT count as module-complete media

The final MMG report MUST evaluate module-local media assets only when deciding whether required media is complete.

#### Scenario: Static fallback exists without module media

- **GIVEN** an NPC has media under `web/static/media/npcs/`
- **AND** the module does not contain matching media under `modules/<module>/media/npcs/`
- **WHEN** the MMG final report audits media completion
- **THEN** the static fallback media MUST NOT satisfy the required module-local media check
- **AND** the asset MUST remain missing if required module-local media is absent.

### Requirement: Sidebar media handoff MUST use authoritative MMG pass as final say

When an authoritative MMG final report states that no required module-local media is missing, the Module Builder sidebar MUST suppress media-generator-needed handoff state even if `toolkit_build_report.json` still contains media-only debt.

#### Scenario: Stale build report with fresh MMG pass

- **GIVEN** `toolkit_build_report.json` contains `structured_monster_media_missing` or `toolkit_manual_media_generation_required`
- **AND** `module_media_generator_report.json` is authoritative with status `pass` and missing count `0`
- **WHEN** the Module Builder sidebar lists the module
- **THEN** the module MUST NOT show `Needs Module Media Generator`
- **AND** it MUST NOT show `Publication blocked: missing media` solely because of the stale build report.

### Requirement: Sidebar media handoff MUST use authoritative MMG fail as final say

When an authoritative MMG final report states that required module-local media remains missing, the Module Builder sidebar MUST show media-generator-needed handoff state even if the build report is stale, ambiguous, or absent.

#### Scenario: MMG final report still has missing media

- **GIVEN** `module_media_generator_report.json` is authoritative with status `fail` and missing count greater than `0`
- **WHEN** the Module Builder sidebar lists the module
- **THEN** the module MUST show `Needs Module Media Generator`
- **AND** it SHOULD show `Publication blocked: missing media` when no higher-priority non-media failure is present.

### Requirement: MMG media authority MUST NOT hide non-media failures

The MMG final report MUST override only media handoff state and MUST NOT suppress semantic, topology, monster-reference, schema, readiness, or publishability failures from the build report.

#### Scenario: Semantic failure with MMG media pass

- **GIVEN** `toolkit_build_report.json` contains a semantic publishability blocker
- **AND** `module_media_generator_report.json` is authoritative with status `pass` and missing count `0`
- **WHEN** the Module Builder sidebar lists the module
- **THEN** the semantic failure MUST remain visible
- **AND** only the media-generator-needed handoff state MAY be suppressed.

### Requirement: Invalid MMG reports MUST fail open to existing behavior

If the MMG final media report is missing, malformed, non-authoritative, or uses an unknown contract version, sidebar behavior MUST fall back to the existing `toolkit_build_report.json`-based logic.

#### Scenario: Malformed MMG report

- **GIVEN** `module_media_generator_report.json` cannot be parsed or lacks the required authority fields
- **AND** `toolkit_build_report.json` is an authoritative media-only debt report
- **WHEN** the Module Builder sidebar lists the module
- **THEN** the existing media handoff behavior MUST remain unchanged.
