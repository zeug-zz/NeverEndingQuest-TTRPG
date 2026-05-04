# Design: Ancients Lab Lovecraftian Narrative Enhancement

## Architecture Decision: Three-Layer Delivery

```
Layer 1: dmInstructions (Location-Level) -- PRIMARY
  - Most immediate impact on Narrator
  - Playline emergence cues per location
  - 12 locations x ~1000 chars each

Layer 2: Plot Points + NPCs (Module-Level) -- SECONDARY
  - Plot point descriptions enriched with multi-interpretation hooks
  - NPC descriptions expanded with playline-specific depth
  - Choice consequences expanded to cover all 5 playlines

Layer 3: LOVECRAFTIAN_NARRATOR_GUIDE.md -- REFERENCE
  - Full 15 ending drafts
  - Playline transition matrix
  - NOT automatically read by Narrator
```

## Key Design Decision: dmInstructions as Primary Vehicle

The `dmInstructions` field exists in all 12 module locations, is explicitly designed for Narrator guidance, and is currently 330-407 chars (well under capacity). It is the ideal place for playline-specific framing because:

1. The LLM Narrator reads it directly upon entering each location
2. It is expressly for DM/Narrator instructions (not player-facing text)
3. It is consumed one location at a time (token-efficient)
4. It accepts freeform text without schema constraints

## Field Selection Rationale

All enriched fields were selected because they are:
- Currently empty (6 NPC descriptions, all 9 role/faction fields) OR
- Currently short and underutilized (dmInstructions at 330-407 chars, descriptions at 308-482 chars) OR
- Explicitly designed for narrative guidance (dmInstructions, plotImpact, adventureSummary)

No fields were selected that carry structural meaning (connectivity, nextPoints, location IDs, monster references, loot tables).

## Playline Emergence Model

The Narrator receives all five playline interpretations but emphasizes one based on player behavior markers:

```
Player Behavior → Emerging Playline
  Cosmic curiosity → DREAMER
  Sealing/containment focus → CONTAINMENT
  Sympathy for mutants → COMMUNION
  Dwarven lineage investigation → INHERITANCE
  Fear expression/reflection → MIRROR
```

Playlines may shift mid-module as players learn more. The dmInstructions provide transition cues when the dominant interpretation changes.

## Ending Selection Model

PP013's enriched description presents all 15 endings (3 per playline) as a decision matrix. The Narrator selects the ending family based on dominant playline, then the specific ending based on cumulative player choices across PP004, PP007, PP008, PP009, and PP012.

```
Dominant Playline → Ending Family (3 variants)
  Choice Pattern → Specific Ending Within Family
    PP004: Reinforce/Communicate/Destroy → positive/neutral/negative tilt
    PP007: Stabilize/Exploit/Hidden → preservation/risk/transformation tilt
    PP012: Repair/Disrupt/Hidden → control/release/transcendence tilt
```

## Migration and Rollback

- All changes are additive text enrichment in existing fields
- BU files are canonical; runtime mirrors regenerate from BU
- Rollback: revert 6 JSON files to pre-edit state; delete the MD guide
- No database migrations, no code changes, no config changes

## Trade-offs

| Trade-off | Decision | Rationale |
|-----------|----------|-----------|
| Many playlines vs. one canon | Keep all five | Enables replay value, rewards player agency |
| JSON vs. MD for endings | Framework in JSON, full drafts in MD | Preserves token budget, full reference available |
| dmInstructions vs. descriptions | Prioritize dmInstructions | Already designed for Narrator guidance |
| Expand all NPCs vs. key NPCs | Expand all 9 | No NPC should be narratively blank |
| New fields vs. existing fields | Existing fields only | Schema stability, validation safety |
