# Design: Resurrection and Corruption State Action

## Prerequisites

This change SHOULD be implemented only after:

- `tt-dead-pc-mechanical-stickiness`
- `tt-supernatural-state-shape-contract`

## Action Shape

**Decision (2026-04-28):** Locked to Option A — a new dedicated `resurrectCharacter` action.

Rationale:
- Resurrection is a supernatural state transition, not a routine mechanical change. A dedicated action makes this unambiguous.
- Structured ops (`updateCharacterInfo.ops`) are for routine mechanics (damage, healing, slot usage). Burying resurrection in ops risks accidental revival through generic ops parsing.
- The codebase already uses dedicated actions for major state transitions: `createEncounter`, `transitionLocation`, `rest`. Resurrection fits this pattern.

```json
{
  "action": "resurrectCharacter",
  "parameters": {
    "character": "Vitreol",
    "mode": "corrupted_resurrection",
    "hitPoints": 1,
    "source": "Voidstone altar",
    "consequences": ["void hunger", "dream contamination"]
  }
}
```

The rejected alternative (Option B: `resurrection_apply` structured op under `updateCharacterInfo`) would have made resurrection opaque and theoretically reachable through generic ops dispatch.

## Required State Effects

The explicit transition MUST:

- confirm the character is currently dead or otherwise eligible,
- set `status` to the intended post-transition state,
- set HP deliberately, never by implicit max-rest behavior,
- reset death saves only because the action is explicit,
- record durable metadata such as `supernatural_state` or lifecycle history,
- preserve auditability in logs or character history.

## Validation

Validation MUST reject:

- generic HP healing of dead PCs,
- resurrection actions without source/mode,
- resurrection actions targeting living characters unless explicitly allowed by mode,
- impossible or unsupported mode values.

## Rollback

Because this is an explicit action/operation, rollback can disable action dispatch while leaving dead-stickiness in place.
