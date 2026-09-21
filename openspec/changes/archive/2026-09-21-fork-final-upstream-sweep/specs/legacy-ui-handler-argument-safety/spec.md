# Legacy UI Handler Argument Safety

## Purpose

Ensure names and structured values passed to inline event handlers in the
legacy facilitator template are serialized and HTML-attribute escaped so that
authored or runtime text can never terminate the attribute or execute as
JavaScript.

## ADDED Requirements

### Requirement: Serialized attribute helper exists and is behaviorally correct

The legacy template SHALL define a `legacyJsonAttribute(value)` helper that
serializes a value with `JSON.stringify` and then applies HTML attribute
escaping, producing a JavaScript expression safe to embed in a quoted HTML
attribute.

#### Scenario: String value round-trips

- **WHEN** `legacyJsonAttribute` receives a string value
- **THEN** the embedded expression SHALL evaluate to the same string at
  runtime
- **AND** the attribute text SHALL contain escaped quotes rather than raw
  quotes

#### Scenario: Structured value round-trips

- **WHEN** `legacyJsonAttribute` receives an object or array
- **THEN** the embedded expression SHALL evaluate to an equivalent structure
  at runtime

#### Scenario: Nullish values are handled safely

- **WHEN** `legacyJsonAttribute` receives `null` or `undefined`
- **THEN** it SHALL return a serialized value without throwing

### Requirement: Inline handler arguments are serialized and escaped

Character, NPC, item, quest, spell, save-game, and archive values passed to
inline event handlers SHALL be embedded through `legacyJsonAttribute` (or an
equivalent fork-native serialization helper).

#### Scenario: Character sheet actions

- **WHEN** the character sheet renders handler arguments for portrait upload,
  portrait create, portrait download, readiness repair, character edit, or PDF
  download
- **THEN** the argument SHALL be embedded through the serialization helper
- **AND** raw `normalizedName` interpolation directly inside a quoted handler
  attribute SHALL NOT remain as the sole protection

#### Scenario: NPC detail actions

- **WHEN** the NPC panel renders `showNPCSaves`, `showNPCSkills`,
  `showNPCInventory`, `showNPCDetailList`, or `showNPCSpells` handler
  arguments
- **THEN** `npc.name` SHALL be embedded through the serialization helper
- **AND** structured payload arguments SHALL be embedded through the same
  helper instead of ad-hoc quote replacement

#### Scenario: Save and archive actions

- **WHEN** save-game or archive entries render `selectSaveGame`,
  `selectArchiveZip`, or `data-save` attribute payloads
- **THEN** the folder name, zip name, and serialized payload SHALL be embedded
  through the serialization helper

### Requirement: Adversarial names cannot execute JavaScript

A display value containing apostrophes, double quotes, angle brackets,
ampersands, backticks, or event-handler-like text SHALL NOT be able to break out
of the handler attribute, terminate the JavaScript string literal, or inject an
executable handler.

#### Scenario: Apostrophe-bearing NPC name

- **WHEN** an NPC name containing an apostrophe (for example `Ma's Ghost`) is
  rendered into a handler argument
- **THEN** the rendered attribute SHALL remain well-formed
- **AND** the handler SHALL receive the original name value

#### Scenario: Event-handler-like value

- **WHEN** a display value resembling an event handler or script fragment is
  rendered into a handler argument
- **THEN** the value SHALL remain inert data
- **AND** no additional handler SHALL be attached

### Requirement: Handler signatures remain stable

Handler serialization SHALL NOT require redesigning handler function
signatures; JSON string and object literals SHALL evaluate to the same runtime
argument values the handlers already accept.

#### Scenario: Existing handler invocation

- **WHEN** an existing handler such as `uploadPortrait(characterName)` is
  invoked from serialized HTML
- **THEN** it SHALL receive the same value type and content as before the
  change
