# Spec: dmInstructions Playline Guidance

## Purpose

Expand the `dmInstructions` field in all 12 module locations to serve as the primary delivery vehicle for playline-specific Narrator guidance, including emergence cues, atmospheric framing, NPC interpretation, and choice presentation.

## ADDED Requirements

### Requirement: All 12 Location dmInstructions Must Be Expanded

Every location in all four areas SHALL have its `dmInstructions` field expanded to a minimum of 750 characters and a maximum of 1200 characters.

| Area | Locations | Target |
|------|-----------|--------|
| BA001 (The Blackcrag Marches) | I01, I02, I03 | 750-850 chars |
| FG001 (The Abandoned Vaultways) | I01, I02, I03 | 900-1000 chars |
| AC001 (The Aberrant Wastes) | I01, I02, I03 | 950-1100 chars |
| TTL001 (The Shuddering Wilds) | I01, I02, I03 | 1100-1200 chars |

#### Scenario: dmInstructions provide emergence cues

- **GIVEN** the Narrator processes a location's `dmInstructions`
- **WHEN** determining which playline to emphasize
- **THEN** the instructions SHALL include behavior-based emergence cues for all five playlines
- **AND** the cues SHALL be formatted as "If players [behavior], lean toward [PLAYLINE]"

#### Scenario: dmInstructions guide NPC interpretation

- **GIVEN** a location with NPC interactions in its `dmInstructions`
- **WHEN** the Narrator presents an NPC
- **THEN** the instructions SHALL include per-playline role interpretations for each NPC in that location
- **AND** the instructions SHALL indicate which NPC behaviors shift based on the emerging playline

### Requirement: dmInstructions Must Follow Standardized Template

Every expanded `dmInstructions` SHALL follow a consistent template:

```
[LOCATION NAME] - [PLAYLINE CUES]

ATMOSPHERE: [Sensory details to emphasize]

PLAYLINE EMERGENCE:
- If players [behavior], lean toward DREAMER
- If players [behavior], lean toward CONTAINMENT
- If players [behavior], lean toward COMMUNION
- If players [behavior], lean toward INHERITANCE
- If players [behavior], lean toward MIRROR

KEY NPC INTERPRETATIONS:
- [NPC name]: [per-playline role]

CHOICE FRAMING:
- When presenting [choice], hint at [playline-specific consequence]
```

#### Scenario: Template provides consistent Narrator experience

- **GIVEN** any location's `dmInstructions`
- **WHEN** processed by the Narrator
- **THEN** the instructions SHALL contain ATMOSPHERE, PLAYLINE EMERGENCE, KEY NPC INTERPRETATIONS, and CHOICE FRAMING sections

### Requirement: TTL001 I03 (Runebound Isolation Cell) Must Be the Convergence Point

TTL001 I03 is where all five playlines converge before the final confrontation. Its `dmInstructions` SHALL be the most detailed, at approximately 1200 characters.

#### Scenario: Runebound Isolation Cell converges all truths

- **GIVEN** the party enters TTL001 I03
- **WHEN** the Narrator reads the `dmInstructions`
- **THEN** the instructions SHALL explicitly state that this is where all five truths meet
- **AND** the instructions SHALL provide Grahl's and Hesk's interpretations for all five playlines
- **AND** the instructions SHALL frame the Prototype Cure decision with all five playline consequences

### Requirement: Area-Level Descriptions Must Be Enriched

Each area's `areaDescription` in the BU file SHALL be expanded:

| Area | Current | Target |
|------|---------|--------|
| BA001 | 257 chars | ~500 chars |
| FG001 | 257 chars | ~550 chars |
| AC001 | 257 chars | ~600 chars |
| TTL001 | 318 chars | ~650 chars |

#### Scenario: areaDescription sets playline-ambiguous tone

- **GIVEN** the Narrator reads an area's `areaDescription`
- **WHEN** the party enters a new area
- **THEN** the description SHALL establish a Lovecraftian atmosphere compatible with all five playlines

## Should Guidance

- dmInstructions SHOULD use more specific sensory language in deeper areas (smells, textures, wrong-geometry)
- Emergence cues SHOULD be behavior-based not mechanical (avoid "if they pass a Perception check")
- The TTL001 area SHOULD have the richest dmInstructions as it is the climax zone
- AdventureSummary fields SHOULD be enriched alongside dmInstructions where relevant
