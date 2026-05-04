# Spec: Plot Point Lovecraftian Enrichment

## Purpose

Enrich `module_plot_BU.json` plot point descriptions, plot impacts, side quest descriptions, and the main objective with Lovecraftian narrative depth and multi-playline interpretation hooks.

## ADDED Requirements

### Requirement: mainObjective Must Be Expanded

The `mainObjective` field SHALL be expanded from 284 chars to approximately 600 chars, adding cosmic horror undertone while preserving the core functional quest description.

#### Scenario: mainObjective conveys cosmic ambiguity

- **GIVEN** the Narrator reads `module_plot_BU.json.mainObjective`
- **WHEN** the main objective is presented
- **THEN** the text SHALL describe the quest in terms that are compatible with all five playline interpretations
- **AND** the text SHALL NOT commit to any single playline truth

### Requirement: Decision Point Plot descriptions Must Be Enriched

The following plot points SHALL have their `description` field enriched with multi-interpretation framing:

| Plot Point | Current | Target |
|-----------|---------|--------|
| PP004 (The Vaults' Secret Heart) | 394 chars | ~700 chars |
| PP007 (Shattered Realities) | 336 chars | ~650 chars |
| PP008 (The Aberrant Conclave) | 394 chars | ~700 chars |
| PP009 (Confronting the Source) | 325 chars | ~700 chars |
| PP012 (Revelations at the Sunken Threshold) | 350 chars | ~800 chars |
| PP013 (The Heart Beneath the Wilds) | 377 chars | ~1200 chars |

#### Scenario: PP013 description provides ending framework

- **GIVEN** the Narrator reads PP013's description
- **WHEN** preparing the final confrontation
- **THEN** the description SHALL present all 15 ending variants (3 per playline) as an accessible decision matrix
- **AND** the description SHALL include guidance on how the dominant playline and cumulative choices determine which ending activates

### Requirement: plotImpact Fields Must Be Expanded

The same plot points' `plotImpact` fields SHALL be expanded to cover multi-playline consequence guidance:

| Plot Point | Current | Target |
|-----------|---------|--------|
| PP004 | 166 chars | ~350 chars |
| PP007 | 122 chars | ~300 chars |
| PP008 | 93 chars | ~350 chars |
| PP009 | 114 chars | ~400 chars |
| PP012 | 74 chars | ~400 chars |
| PP013 | 106 chars | ~500 chars |

#### Scenario: plotImpact covers all five playline consequences

- **GIVEN** an enriched plotImpact field
- **WHEN** the Narrator evaluates a choice
- **THEN** the field SHALL describe how the choice's consequences differ across all five playline interpretations

### Requirement: Side Quest descriptions Must Be Enriched

At least 12 of the 24 side quests SHALL have their `description` field enriched with Lovecraftian flavour. Prioritized side quests include:

- SQ002 (Whispering Stones), SQ006 (Murals of Warning), SQ008 (Fragments of Memory)
- SQ012 (Echoes of the Past), SQ013 (The Reality Anchor), SQ014 (The Outcast's Plea)
- SQ017-SQ024 (all Shuddering Wilds side quests)

Target: ~350 chars per enriched side quest description.

#### Scenario: Side quest descriptions carry playline flavour

- **GIVEN** a side quest description in `module_plot_BU.json`
- **WHEN** the Narrator presents the side quest hook
- **THEN** the description SHALL include atmospheric detail consistent with the module's Lovecraftian tone
- **AND** the description SHALL NOT break the side quest's mechanical function

## Should Guidance

- PP001-PP003, PP005, PP006, PP010-PP011 descriptions SHOULD be reviewed for minor flavour additions but are not primary targets
- Side quest descriptions SHOULD prioritize those with mutation/ancestry/dream/mirror/containment themes
- plotImpact expansions SHOULD use a consistent format: one sentence per playline consequence
