# Legacy UI Literal Output Safety

## Purpose

Ensure authored and runtime display values in the legacy facilitator template
(`web/templates/game_interface.html`) are HTML-escaped before insertion into
HTML text and attribute contexts, while ordinary game content remains visibly
unchanged.

## ADDED Requirements

### Requirement: Legacy HTML escaping helper exists and is behaviorally correct

The legacy template SHALL define an `escapeLegacyHtml(value)` helper that
returns a string safe for insertion into HTML text and quoted HTML attribute
contexts.

#### Scenario: Adversarial value is escaped

- **WHEN** `escapeLegacyHtml` receives a value containing `&`, `<`, `>`, `"`,
  `'`, or a backtick, or text resembling an event handler
- **THEN** the returned string SHALL contain the corresponding HTML entities
  and SHALL NOT contain the raw escaping-sensitive characters

#### Scenario: Ordinary value remains readable

- **WHEN** `escapeLegacyHtml` receives an ordinary name such as `Kira` or
  `Blarg`
- **THEN** the rendered DOM text SHALL be the original value unchanged

#### Scenario: Nullish and numeric values are handled safely

- **WHEN** `escapeLegacyHtml` receives `null`, `undefined`, or a number
- **THEN** it SHALL return a string without throwing

### Requirement: High-risk display values are escaped before HTML insertion

Values that originate from character, NPC, item, quest, spell, save-game, or
archive data SHALL be passed through `escapeLegacyHtml` before insertion into
HTML text or HTML attribute contexts, including tooltip titles and tooltip
content.

#### Scenario: NPC and item display text

- **WHEN** the character sheet, NPC panel, inventory, or storage panel renders
  a data-derived name or description into `innerHTML`
- **THEN** the value SHALL be inserted through `escapeLegacyHtml`
- **AND** no raw `npc.name`, `item.item_name`, or description value SHALL be
  inserted directly

#### Scenario: Tooltip and attribute values

- **WHEN** a `data-tooltip-title` or `data-tooltip-content` attribute is
  rendered from a data-derived value
- **THEN** the value SHALL be inserted through `escapeLegacyHtml`
- **AND** quote-only `.replace(/"/g, '&quot;')` escaping SHALL NOT be the sole
  protection for that value

#### Scenario: Save and archive display values

- **WHEN** save-game or archive records render folder names, zip names, or
  descriptions
- **THEN** the display text SHALL be inserted through `escapeLegacyHtml`

### Requirement: Documented exceptions remain intact

Intentional markup assembly (for example `'<br>'` joining inside tooltip
composition) SHALL remain outside escaping, and intentional chart/markup HTML
SHALL NOT be converted to visible entity text.

#### Scenario: Tooltip line composition

- **WHEN** tooltip parts are joined with intentional markup before escaping
- **THEN** the join markup SHALL remain functional
- **AND** each data-derived part SHALL still be escaped before joining

### Requirement: Escaping does not replace identity normalization

Canonical identity normalization (portrait slugs and routing names) SHALL
remain in effect; escaping SHALL NOT be substituted for normalization.

#### Scenario: Portrait and routing values

- **WHEN** a normalized slug is used for portrait or routing actions
- **THEN** the existing normalization behavior SHALL be preserved
- **AND** the value SHALL additionally be attribute-safe when embedded in HTML
