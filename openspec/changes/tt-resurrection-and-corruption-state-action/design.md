# Design: Resurrection and Corruption State Action

## Prerequisites

This change SHOULD be implemented only after:

- `tt-dead-pc-mechanical-stickiness`
- `tt-supernatural-state-shape-contract`

## Action Shape Options

Two acceptable designs are possible. The builder should choose the smallest correct design after inspecting current action patterns.

### Option A: New action

Example:

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

### Option B: Structured operation

Example:

```json
{
  "action": "updateCharacterInfo",
  "parameters": {
    "characterName": "Vitreol",
    "ops": [
      {
        "op": "resurrection_apply",
        "mode": "corrupted_resurrection",
        "hitPoints": 1,
        "source": "Voidstone altar"
      }
    ]
  }
}
```

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
