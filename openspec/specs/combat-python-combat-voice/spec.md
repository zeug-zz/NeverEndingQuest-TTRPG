# combat-python-combat-voice Specification

## Purpose
Defines a concise, human-sounding Narrator or Dungeon Master voice for combat replies authored by Python, without transferring mechanical authority or response decisions to the model.

## Requirements

### Requirement: Python-authored combat chat replies SHALL use the Narrator voice

User-facing replies produced by Python combat command handlers SHALL use the established Narrator or Dungeon Master voice, remain concise, and report only authoritative mechanics and state.

#### Scenario: A Python combat command returns feedback
- **WHEN** `/att`, `/dmg`, `/init`, `/end`, `/cmd`, or another combat command produces user-facing chat
- **THEN** the reply SHALL read as a concise Narrator or Dungeon Master response
- **AND** internal debug diagnostics SHALL NOT be emitted as chat text
- **AND** the command's mechanics, state changes, and provider-call behavior SHALL remain unchanged except where this change specifies otherwise

#### Scenario: A reply reports a mechanical result
- **WHEN** Python reports an attack, damage, command rejection, or phase transition
- **THEN** the reply SHALL agree with the authoritative parsed result and persisted state
- **AND** it SHALL NOT claim an effect that was not applied

### Requirement: `/cmd` feedback SHALL preserve the chat illusion without a new reply call

Python SHALL acknowledge accepted, rejected, and invalid `/cmd` directives with concise Narrator-voice feedback, while ally dialogue SHALL use the ally batch's existing narration request.

#### Scenario: A valid directive receives feedback
- **WHEN** Python accepts a `/cmd` directive
- **THEN** the UI SHALL acknowledge that the directive was received in the Narrator voice
- **AND** the next ally-batch narration MAY include a brief in-character response from the named ally when it matches the accepted ledger
- **AND** no provider request SHALL be added solely to acknowledge the command

#### Scenario: A directive is rejected
- **WHEN** Python rejects an unknown, inactive, malformed, or out-of-bounds directive
- **THEN** its user-facing response SHALL explain the rejection in the Narrator voice
- **AND** it SHALL NOT expose raw parser diagnostics or claim that an ally received the directive

### Requirement: Narrator-voice formatting SHALL not change combat decisions

Python reply formatting SHALL remain presentation-only; any optional flavor on constrained or regex-derived responses SHALL NOT alter the parsed command, accepted mechanics, state mutation, or provider-call budget.

#### Scenario: Flavor is added to a constrained reply
- **WHEN** a Python reply adds short combat flavor to a constrained result
- **THEN** its mechanical values and meaning SHALL remain identical to the authoritative result
- **AND** no extra provider request or state write SHALL occur
