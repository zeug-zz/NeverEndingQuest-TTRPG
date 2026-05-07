## ADDED Requirements

### Requirement: Natural-language parser runtime SHALL be feature-flag gated

The multi-PC combat runtime SHALL invoke the PC_PHASE natural-language parser only when `COMBAT_PC_PHASE_NL_FAST_PATH` is enabled.

#### Scenario: Parser flag disabled preserves existing fallback
- **GIVEN** `COMBAT_PC_PHASE_NL_FAST_PATH` is `False`
- **AND** multi-PC combat is in `PC_PHASE`
- **WHEN** the facilitator enters natural-language prose that is not a slash command
- **THEN** runtime SHALL NOT call `parse_pc_phase_action(...)`
- **AND** the input SHALL proceed through the existing full combat LLM path when no other deterministic gate handles it

#### Scenario: Parser flag enabled allows parser attempt
- **GIVEN** `COMBAT_PC_PHASE_NL_FAST_PATH` is `True`
- **AND** multi-PC combat is in `PC_PHASE`
- **WHEN** the facilitator enters non-command prose
- **THEN** runtime MAY call `parse_pc_phase_action(...)`
- **AND** parser fallback SHALL preserve the existing full combat LLM path

### Requirement: Local combat command handler SHALL always return the full command tuple

`MultiPCCombatManager.handle_combat_command(...)` SHALL always return exactly four values representing mechanical feedback, spoken narration, history log, and skip-LLM decision.

#### Scenario: Unsupported command falls through safely
- **WHEN** `handle_combat_command(...)` receives an unsupported or unrecognized command
- **THEN** it SHALL return `(None, None, None, False)`
- **AND** the combat loop SHALL NOT crash while unpacking the result

### Requirement: Parser success SHALL only be reported after deterministic mutation succeeds

Natural-language parser handled results SHALL not be shown as committed until all required deterministic mutations have succeeded.

#### Scenario: Encounter mutation fails
- **GIVEN** a parser result includes enemy encounter ops
- **WHEN** applying those ops fails
- **THEN** runtime SHALL NOT print an applied mechanical report
- **AND** runtime SHALL NOT append an `[ALREADY_APPLIED]` history record for that parser result
- **AND** runtime SHALL NOT record a ledger event for that parser result
- **AND** runtime SHALL either fall back to existing combat LLM handling or emit user-safe failure guidance

#### Scenario: Character mutation fails
- **GIVEN** a parser result includes PC or allied NPC character ops
- **WHEN** applying those ops fails
- **THEN** runtime SHALL NOT claim the action was applied
- **AND** runtime SHALL NOT skip into false success

#### Scenario: Parser mutation succeeds
- **WHEN** all parser-required deterministic mutations succeed
- **THEN** runtime MAY print `[skipTTS]` mechanical feedback
- **AND** runtime MAY print spoken narration
- **AND** runtime MAY append `[ALREADY_APPLIED]` history
- **AND** runtime MAY record historical ledger facts

### Requirement: Parser spell and healing resource handling SHALL be conservative

Natural-language parser spell and healing fast paths SHALL apply only when required resources and target state are proven safe.

#### Scenario: Magic Missile slot unavailable or unknown
- **GIVEN** Magic Missile prose has explicit target damage allocation
- **WHEN** the caster spell slot availability cannot be proven or no valid casting source exists
- **THEN** the parser SHALL NOT apply enemy damage
- **AND** runtime SHALL fall back or surface user-safe guidance

#### Scenario: Magic Missile slot spend succeeds
- **GIVEN** Magic Missile prose has explicit target damage allocation
- **AND** the caster has an available level 1 or higher spell slot or valid casting source
- **WHEN** parser fast-path handling is enabled
- **THEN** enemy damage SHALL be applied deterministically
- **AND** caster slot spend SHALL be applied deterministically where supported

#### Scenario: Ordinary healing targets a mechanically dead PC
- **GIVEN** authoritative character state says the target is mechanically dead
- **WHEN** prose attempts ordinary healing without resurrection authority
- **THEN** the parser SHALL NOT apply HP healing
- **AND** the parser SHALL NOT clear death state
- **AND** runtime SHALL fall back or surface user-safe guidance

#### Scenario: Healing slot availability cannot be proven
- **GIVEN** healing prose names a spell such as Cure Wounds or Healing Word
- **WHEN** caster slot availability cannot be proven
- **THEN** the parser SHALL NOT apply healing or slot spend as committed mechanics
- **AND** runtime SHALL fall back or surface user-safe guidance

### Requirement: Runtime combat prompts SHALL not contain residual PC_PHASE contradictions

The compressed runtime combat generation prompt SHALL not contain legacy instructions that contradict the `PC_PHASE` active-PC-only model.

#### Scenario: PC_PHASE continuation text is absent
- **WHEN** prompt source-contract tests inspect `combat_sim_prompt_multipc_compressed.txt`
- **THEN** they SHALL fail if the prompt tells PC_PHASE handling to continue processing remaining NPCs or monsters
- **AND** they SHALL pass only when PC_PHASE resolves the active PC, then stops or requests a roll

#### Scenario: Enemy phase batch strictness remains
- **WHEN** prompt source-contract tests inspect combat prompts
- **THEN** they SHALL still find ENEMY_PHASE batch language requiring enemies and allied NPCs to resolve in batch

### Requirement: updateEncounter consolidation wording SHALL be conditional, not universal

Combat prompts SHALL use the rule `at most one updateEncounter when enemy state changes exist` rather than a universal exact-one requirement.

#### Scenario: Compressed generation prompt has conditional wording
- **WHEN** source-contract tests inspect `combat_sim_prompt_multipc_compressed.txt`
- **THEN** they SHALL find conditional `at most one updateEncounter` wording
- **AND** they SHALL reject universal `EXACTLY ONE updateEncounter per response` requirements

#### Scenario: Compressed validation prompt has conditional wording
- **WHEN** source-contract tests inspect `combat_validation_prompt_multipc_compressed.txt`
- **THEN** they SHALL find conditional `at most one updateEncounter` wording
- **AND** they SHALL reject universal exact-one language except when clearly scoped to a multiple-updateEncounter violation example

### Requirement: Closure validation SHALL include all dependent combat PC phase changes

The closure change SHALL not be considered complete until the dependent combat PC phase changes and deterministic death-save spec still validate.

#### Scenario: Closure validation gate runs all related validations
- **WHEN** implementation is complete
- **THEN** `openspec validate combat-pc-phase-contract-closure` SHALL pass
- **AND** `openspec validate combat-pc-phase-prompt-alignment` SHALL pass
- **AND** `openspec validate combat-pc-phase-action-ledger` SHALL pass
- **AND** `openspec validate combat-pc-phase-fast-path` SHALL pass
- **AND** `openspec validate combat-pc-phase-natural-language-parser` SHALL pass
- **AND** `openspec validate tt-deterministic-combat-death-saves` SHALL pass
