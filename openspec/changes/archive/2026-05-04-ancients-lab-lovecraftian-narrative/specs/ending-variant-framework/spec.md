# Spec: Ending Variant Framework

## Purpose

Define the 15-ending framework (3 per playline) embedded in PP013's description and detailed in the standalone LOVECRAFTIAN_NARRATOR_GUIDE.md.

## ADDED Requirements

### Requirement: PP013 Description Must Contain Ending Matrix

The PP013 `description` field SHALL present all 15 ending variants as a decision matrix accessible to the Narrator.

#### Scenario: Narrator reads ending matrix

- **GIVEN** the Narrator reads PP013's expanded description
- **WHEN** preparing the final confrontation
- **THEN** the description SHALL identify which ending family (Dreamer/Containment/Communion/Inheritance/Mirror) is active
- **AND** the description SHALL present the 3 variant endings within that family
- **AND** the description SHALL include guidance on how PP004, PP007, PP008, PP009, and PP012 choices tilt toward specific endings

### Requirement: All 15 Endings Must Be Named and Defined

The following endings SHALL be defined:

**Dreamer Family:**
- A1: The Dreamer Returns to Sleep (neutral/minimal change)
- A2: The Dreamer Wakens (catastrophic transformation of the region)
- A3: You Become the Dream (party merges with the dreaming consciousness)

**Containment Family:**
- B1: The Warden Endures (containment holds, Thing survives)
- B2: The Seal Breaks (containment fails, what-lies-below emerges)
- B3: You Become the New Warden (party sacrifices to maintain the seal)

**Communion Family:**
- C1: Communion Completed (humanity joins the precursor consciousness)
- C2: Communion Rejected (the Thing dies alone, last of its kind)
- C3: Partial Communion (new symbiotic state, neither fully human nor fully Other)

**Inheritance Family:**
- D1: The Cycle Continues (dwarves remain mortal, reversion will recur)
- D2: The Reversion Completes (dwarves remember their true nature)
- D3: A New Separation (unprecedented third path, neither mortal nor reverted)

**Mirror Family:**
- E1: The Mirror Shatters (fear destroyed, self-knowledge lost)
- E2: The Mirror Holds (party navigates their reflections safely)
- E3: You Become the Mirror (party becomes the next generation's test)

#### Scenario: Every ending has a distinct narrative outcome

- **GIVEN** any of the 15 ending variants
- **WHEN** the Narrator resolves PP013
- **THEN** the ending SHALL have a distinct narrative outcome that is incompatible with any other ending
- **AND** the ending SHALL describe the fate of the Thing, the region, and the party

### Requirement: LOVECRAFTIAN_NARRATOR_GUIDE.md Must Be Created

A standalone reference guide SHALL be created at `modules/The_Ancients_Lab/LOVECRAFTIAN_NARRATOR_GUIDE.md` containing:

1. Full 300-500 word narration drafts for each of the 15 endings
2. Playline transition matrix (how playlines blend and shift mid-module)
3. Area-by-area atmospheric reference for each playline
4. NPC quick reference table with per-playline interpretation
5. Atmospheric phrase bank for the Narrator

#### Scenario: Guide serves as reference for full ending text

- **GIVEN** the LOVECRAFTIAN_NARRATOR_GUIDE.md file
- **WHEN** a developer or Narrator needs the full ending text
- **THEN** the guide SHALL provide detailed narration drafts for all 15 endings
- **AND** the guide SHALL NOT be required at runtime (JSON fields carry sufficient framework)

### Requirement: Ending Selection Must Be Deterministic

The Narrator SHALL select the ending family based on the dominant playline, then the specific end variant based on cumulative player choices.

#### Scenario: Playline dominance determines ending family

- **GIVEN** a gameplay session reaching PP013
- **WHEN** the Narrator selects the ending
- **THEN** the ending family SHALL match the playline that received the most emergence triggers
- **AND** in case of tie, the most recently triggered playline SHALL take precedence

#### Scenario: Choice pattern selects specific variant

- **GIVEN** the dominant playline for PP013
- **WHEN** resolving the specific ending variant within that family
- **THEN** a "reinforce/seal/preserve" choice pattern across PP004/PP007/PP009/PP012 SHALL select the first variant (return to stasis)
- **AND** a "destroy/disrupt/break" pattern SHALL select the second variant (catastrophic change)
- **AND** a "communicate/enter/transcend" pattern SHALL select the third variant (transformation)

## Should Guidance

- Ending narration SHOULD echo imagery and themes established earlier in the module
- The Guide SHOULD include transitional language for blending playlines when the dominant interpretation shifts
- Ending narration drafts SHOULD be ASCII-only (no Unicode characters)
- The atmospheric phrase bank SHOULD provide 5-8 reusable phrases per playline family
