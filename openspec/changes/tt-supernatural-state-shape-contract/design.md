# Design: Supernatural State Shape Contract

## Prime Directive

Python enforces reality; the DM interprets it.

The prompt contract should not suppress weird narration. It should require durable supernatural claims to choose one of four shapes.

## State Shapes

1. Dead PC remains dead.
   - The PC can be carried, mourned, targeted by resurrection, dreamed about, or echoed spiritually.
   - No HP/rest/healing implication changes death.

2. Separate entity.
   - A corpse-thrall, echo, simulacrum, possessed shell, or corrupted vessel exists separately from the dead PC.
   - It needs scene-anchor/NPC/combatant/follower state if durable.

3. Corrupted or undead PC resurrection.
   - The PC returns as playable or semi-playable with explicit mechanical transition.
   - This requires a future dedicated state action.

4. Dream, vision, echo, or foreshadowing.
   - No durable state change.
   - Must be framed as subjective, symbolic, distant, remembered, dreamed, sensed, or foreshadowed.

## Prompt Strategy

Add compact compressed and full-prompt guidance. The compressed prompt can use a directive such as `@DEATH_AND_SUPERNATURAL_STATE`. The full prompt should explain the same principle in prose.

## Validation Strategy

Validation should look for durable claims like return-to-life, present corrupted body, party-following thrall, or changed PC nature. If a response makes those claims without matching actions, validation should request one of:

- keep PC dead and frame as dream/vision/echo,
- create/move separate entity via available state action,
- use future resurrection/corruption action once available.

Until the future action exists, validator wording should avoid instructing the model to invent unsupported action names.

## Rollback

Prompt sections are additive and can be removed independently from runtime code.
