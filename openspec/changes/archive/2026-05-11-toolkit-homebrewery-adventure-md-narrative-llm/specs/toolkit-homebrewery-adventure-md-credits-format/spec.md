## Purpose

Define the updated credits section format using the `{{credits}}` snippet combined with a `{{wide}}` block for full-width layout, including NEQ-TTRPG Module Builder attribution, author/source/license information (derived from `module_context.json`), and SRD 5.2.1 attribution.

The exact output format SHALL be:

```
{{credits}}

{{wide
# Credits
**Module adapted for NeverEndingQuest**

**Module Builder:** [NEQ-TTRPG](https://github.com/zeug-zz/NeverEndingQuest-TTRPG)

**Author:** {display_name}

**Source:** [{source_url}]({source_url})

**License:** [{license_url}]({license_url})

*Portions derived from SRD 5.2.1, CC BY 4.0.*
}}
```

## ADDED Requirements

### Requirement: SHALL use {{credits}} snippet with {{wide}} block wrapper

The `_build_credits()` function SHALL emit the `{{credits}}` V3 snippet on its own line, followed by a `{{wide` block opening on the next line. The `# Credits` H1 heading SHALL appear inside the wide block. The block SHALL close with `}}` on its own line.

#### Scenario: Credits format has both snippets

**Given** the credits section is generated
**When** a module has author and license data
**Then** the output SHALL contain `{{credits}}` followed by `{{wide` on the next line, and SHALL close with `}}` on its own line

### Requirement: SHALL include Module adapted and Module Builder attributions

The credits wide block SHALL include `**Module adapted for NeverEndingQuest**` followed by `**Module Builder:** [NEQ-TTRPG](https://github.com/zeug-zz/NeverEndingQuest-TTRPG)` as markdown.

#### Scenario: Module Builder link present

**Given** the credits section is generated
**When** the module has author data
**Then** the output SHALL contain `**Module Builder:** [NEQ-TTRPG](https://github.com/zeug-zz/NeverEndingQuest-TTRPG)`

### Requirement: SHALL include author, source, and license as markdown links

The credits SHALL display `**Author:** {display_name}`, `**Source:** [{source_url}]({source_url})` as a markdown link where the display text is the URL itself, and `**License:** [{license_url}]({license_url})` as a markdown link where the display text is the URL itself.

#### Scenario: Source and license as URL-as-text markdown links

**Given** the module has `"author": "Kuhal - Module derived from https://homebrewery.naturalcrit.com/share/SyBdnURLNZ"` and `"license": "https://creativecommons.org/licenses/by-nc-sa/4.0/"`
**When** the credits section is generated
**Then** the output SHALL contain `**Author:** Kuhal`, `**Source:** [https://homebrewery.naturalcrit.com/share/SyBdnURLNZ](https://homebrewery.naturalcrit.com/share/SyBdnURLNZ)`, and `**License:** [https://creativecommons.org/licenses/by-nc-sa/4.0/](https://creativecommons.org/licenses/by-nc-sa/4.0/)`

### Requirement: SHALL include SRD 5.2.1 attribution

The credits wide block SHALL include the line `*Portions derived from SRD 5.2.1, CC BY 4.0.*` before the closing `}}`.

#### Scenario: SRD attribution present

**Given** the credits section is generated
**When** the module has author and license data
**Then** the output SHALL contain `Portions derived from SRD 5.2.1, CC BY 4.0`

### Requirement: SHALL remove _license_link_text helper

The `_license_link_text()` helper function SHALL be removed. The license markdown link uses the URL itself as display text (`[URL](URL)`), so no display-text derivation is needed.

#### Scenario: _license_link_text no longer exists

**Given** the updated `utils/homebrewery_adventure_writer.py` module
**When** the module is imported
**Then** the function name `_license_link_text` SHALL NOT be present
