## Context

Combat runtime currently injects several context blocks into the combat prompt: current phase, initiative tracker, party status, active-PC context, and required response instructions. These blocks were added incrementally across multiple stabilization passes. They now sometimes contradict each other, especially during ENEMY_PHASE where PCs are forbidden actors but active-PC override language can remain visible.

Fast-lane combat commands are deterministic Python mechanics. Their output is useful for narration, but the model must treat it as already-committed state, not a request to apply mechanics again.

The combat exit guard is deterministic but currently evaluates only current encounter state. It must evaluate a limited proposed post-response state to avoid rejecting correct final-round responses.

## Contract Layer (MUST)

### Phase Authority

- ENEMY_PHASE prompt context MUST NOT include `CRITICAL OVERRIDE` language that says a PC can act now.
- ENEMY_PHASE prompt context MUST NOT mark a PC as `[>] CURRENT TURN`.
- PC_PHASE prompt context MUST identify only the active PC as the legal actor.
- PC_PHASE prompt instructions MUST NOT direct enemy/NPC batch processing.
- Combat prompts MUST state that `CURRENT_PHASE` overrides turn markers.

### Deterministic Command Replay Protection

- Python-applied `/dmg` and resolved `/att` results MUST be marked as already applied in combat history.
- Already-applied messages MUST use wording that reports committed state, such as `Result HP`, rather than ambiguous unresolved event text.
- Combat generation prompts MUST forbid emitting mechanical ops for the same HP, hit, miss, ammo, or status result described by `[ALREADY_APPLIED]`.
- Deterministic validation MUST reject duplicate same-target same-amount HP ops when they only replay an `[ALREADY_APPLIED]` result.

### Exit Post-Ops Resolution

- Combat exit guards MUST simulate supported same-response `updateEncounter.ops` before rejecting `exit` solely because hostiles are currently alive.
- Simulation MUST support at least `hp_delta`, `set_hp`, and `set_status` for enemy targets.
- Simulation MUST use strict integer parsing; malformed relevant HP values MUST make simulation indeterminate rather than defaulting to zero.
- If current hostiles remain and simulation is indeterminate, the guard MUST reject exit with correction guidance.
- If simulated post-response state contains no living hostiles, the guard MUST allow exit to proceed to the existing action handling path.

## Guidance Layer (SHOULD)

### Phase Cleanup Approach

Prefer making existing formatting helpers phase-aware rather than adding more downstream prompt overrides:

- `format_pc_context_for_prompt()` should return critical override text only during PC_PHASE.
- `format_party_turn_summary()` should suppress active PC markers during ENEMY_PHASE.
- `_get_combatant_marker()` should not mark PCs as current turn while `pc_phase_complete` is true.
- `_determine_instruction_block()` should be simplified to PC-only instructions in PC_PHASE and batch-only instructions in ENEMY_PHASE.

### Replay Guard Scope

Start with a narrow duplicate-damage guard:

- Same enemy target.
- Same damage amount.
- Immediate or recent `[ALREADY_APPLIED]` deterministic command result.
- No explicit new damage source in the user input.

Do not conflate this with existing resume replay detection, which protects crash/reload idempotency rather than active-turn duplicate ops.

### Exit Simulation Scope

Keep simulation conservative. Unknown relevant target names, malformed HP values, or unsupported ops should not accidentally allow exit while current hostiles remain.

## Rollback

- Phase-context cleanup can be rolled back per helper while keeping prompt-source tests disabled temporarily.
- Replay guard can be narrowed to `/dmg` only if `/att` marking causes unexpected narration changes.
- Exit simulation can be limited to `set_status: dead|defeated` if HP simulation causes false positives.
