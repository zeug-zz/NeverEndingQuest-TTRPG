## Context

The combat PC phase enhancement plan introduced a tiered model:

1. Python-owned deterministic slash command fast paths.
2. Conservative natural-language parsing for complete, simple PC actions.
3. Full combat LLM fallback for ambiguous or complex actions.

The model is sound, but the audit found closure gaps where implementation and tests are not yet strict enough to safely archive the workstream.

This change is intentionally small. It does not add new gameplay features. It makes the current contracts true in runtime, prompts, and tests.

## Contract Layer (MUST)

### Natural-Language Parser Gate

- Runtime MUST check `COMBAT_PC_PHASE_NL_FAST_PATH` before invoking the natural-language parser.
- The parser MUST remain disabled by default.
- When disabled, natural-language PC_PHASE prose MUST follow the same fallback path as before the parser was added.

### Command Result Contract

- `MultiPCCombatManager.handle_combat_command(...)` MUST always return exactly four values:
  - mechanical feedback
  - spoken narration
  - history log
  - skip LLM boolean
- Unhandled commands MUST return `(None, None, None, False)`.
- Callers MUST NOT rely on variable tuple length.

### Parser Apply Ordering

- Parser output MUST NOT print mechanical feedback or spoken narration until deterministic mutation succeeds.
- Parser output MUST NOT append `[ALREADY_APPLIED]` history until deterministic mutation succeeds.
- If mutation fails, runtime MUST either fall back to the full combat LLM or emit user-safe failure guidance and continue without claiming committed mechanics.
- Ledger events MUST be recorded only for confirmed already-applied mechanics.

### Parser Resource And State Checks

- Magic Missile fast-path handling MUST spend a caster slot only when an available slot or valid special casting source is proven.
- If spell slot availability cannot be proven, Magic Missile MUST fall back rather than silently omitting slot spend.
- Healing fast-path handling MUST load authoritative target character state for PCs/allied NPCs before applying ordinary healing.
- Ordinary healing MUST NOT clear or bypass mechanical death.
- Healing spell slot spend MUST only be claimed when the caster resource mutation succeeds or availability is proven.

### Prompt Closure

- Runtime compressed generation prompt MUST NOT contain PC_PHASE instructions that say to continue into enemy or allied NPC turns.
- Runtime compressed generation and validation prompts MUST NOT contain universal `EXACTLY ONE updateEncounter` requirements.
- The correct rule is: at most one `updateEncounter` when enemy state changes exist.
- ENEMY_PHASE batch strictness MUST remain intact.

### Regression Tests

- Source-contract tests MUST assert the absence of known bad prompt strings, not only presence of desired strings.
- Runtime/source tests MUST prove the parser hook is feature-flag gated.
- Parser tests MUST cover unavailable spell slot fallback and dead-target healing fallback using authoritative character state or a safe test seam.
- Regression tests MUST cover unhandled command return shape.

## Guidance Layer (SHOULD)

### Parser Application Result

Prefer changing `apply_pc_phase_parse_result(...)` from a plain boolean to a small result object or tuple such as:

```python
{
    "applied": True,
    "fallback_reason": "",
    "error_message": ""
}
```

If minimizing churn is preferred, a boolean return is acceptable only if all exceptions and failed update helper returns are converted into `False`.

### Feedback Emission Pattern

Recommended combat manager order:

1. Parse action.
2. If not handled, log fallback reason and continue to existing LLM path.
3. Apply deterministic mutation.
4. If apply failed, surface safe guidance or continue to existing LLM path.
5. Print mechanical feedback.
6. Print spoken narration.
7. Append `[ALREADY_APPLIED]` history.
8. Persist encounter state and continue input loop.

### Prompt Test Pattern

Negative tests should check for exact legacy fragments such as:

- `continue processing remaining NPCs/monsters`
- `EXACTLY ONE updateEncounter per response consolidating ALL enemy changes`
- `System requires exactly ONE`

When an exact fragment is intentionally retained as an error-template example, it must be qualified so the test can distinguish universal requirements from examples about multiple updateEncounter violations.

## Rollback

- Keep `COMBAT_PC_PHASE_NL_FAST_PATH = False` to disable parser behavior.
- If parser application hardening is risky, revert the parser hook while keeping the command four-tuple fix.
- If prompt edits regress ENEMY_PHASE, revert only the prompt text and keep runtime safety fixes.
