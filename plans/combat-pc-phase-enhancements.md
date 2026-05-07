# Combat PC Phase Enhancements Plan

**Status:** Draft for review  
**Priority:** High (Gameplay Speed and Tabletop UX)  
**Effort:** Medium-Large (~4-7 focused implementation passes)  
**Created:** 2026-05-07  
**Source:** Combat prompt/runtime audit of compressed multi-PC combat prompt, validation prompt, `combat_manager.py`, and `multi_pc_combat.py`

## Objective

Make multi-PC `PC_PHASE` faster and smoother without breaking the tabletop authority model.

The current tabletop design is correct:

> Human DM owns PC_PHASE. LLM DM owns ENEMY_PHASE.

The implementation still carries too much legacy single-PC/LLM-turn architecture. Simple player actions can still run through the full combat LLM, full combat validator, and sometimes secondary updater LLMs. This makes common actions such as `/dmg`, missed `/att`, spell slot spends, healing requests, and narrated melee slower than they need to be.

This plan introduces a tiered PC-phase execution model:

1. Deterministic command narration for Python-owned mechanics.
2. Structured natural-language parsing for simple complete PC actions.
3. Full combat LLM only for genuinely ambiguous or complex combat adjudication.

Core principle:

> Python enforces combat reality; LLM narration interprets it only when needed.

## Executive Summary

The fastest safe improvement is to stop sending deterministic PC-phase command results through the full combat LLM and validator by default.

Current slow path for many PC actions:

```text
Human DM input
  -> combat LLM generation
  -> JSON parse
  -> deterministic integrity checks
  -> combat validation LLM
  -> action processing
  -> optional updateCharacterInfo LLM
  -> optional updateEncounter LLM
  -> state save and sync
```

Target fast path for deterministic commands:

```text
Human DM command
  -> Python applies or confirms mechanics
  -> Python emits [skipTTS] mechanical report
  -> Python emits short DM Voice narration
  -> append compact PC_PHASE event ledger entry
  -> wait for next facilitator input
```

The user-facing result should be immediate.

Example missed attack:

```text
[skipTTS] Dungeon Master: Miss. Rolled 9 vs AC 14. Attack result committed.
Dungeon Master: Acheron's axe whistles past the skeleton as it jerks sideways, bone scraping stone.
```

Example damage:

```text
[skipTTS] Dungeon Master: Damage applied: 8. Skeleton_2 HP 6 -> 0. Target defeated.
Dungeon Master: Acheron's axe crashes through the skeleton's ribs, scattering old bones across the flagstones.
```

The first line is operator/mechanical truth. It should not be spoken by TTS. The second line is narrative and can be spoken by DM Voice.

## Current Combat Architecture

### Runtime Prompt Authority

Multi-PC combat runtime uses compressed prompts only:

- `core/managers/combat_manager.py` loads `prompts/combat/combat_sim_prompt_multipc_compressed.txt` for multi-PC generation.
- `core/managers/combat_manager.py` loads `prompts/combat/combat_validation_prompt_multipc_compressed.txt` for multi-PC validation.
- Uncompressed prompts are documentation/parity mirrors and should follow compressed behavior after cleanup.

### Current Round Flow

```text
Combat created by createEncounter
  -> Python builds encounter
  -> Python rolls DM group initiative
  -> combat loop waits for /init <1-20>

If PC group wins:
  -> PC_PHASE
  -> facilitator chooses PC order and active tabs
  -> facilitator enters /att, /dmg, spells, movement, narrated melee, etc.
  -> /end hands phase to LLM

If DM group wins or /end is entered:
  -> ENEMY_PHASE
  -> LLM resolves enemies and allied NPCs in batch
  -> validation checks response
  -> updateEncounter/updateCharacterInfo actions apply
  -> round advances or control returns to PC_PHASE
```

### Current PC_PHASE Fast-Lane Behavior

Already efficient:

- `/att` hit compares roll vs AC in Python and prompts for `/dmg` without LLM.
- `/switch_pc_focus` refreshes active PC without LLM.
- Death save input gate resolves in Python before combat LLM.

Still inefficient:

- `/att` miss falls through to combat LLM for narration.
- `/dmg` applies HP in Python, then falls through to combat LLM for narration.
- Natural-language attacks and spells use full combat LLM and validation even when all mechanical facts are supplied.
- Missing structured `ops` can trigger secondary updater LLMs.

## Confirmed Problems

### Problem 1: PC_PHASE Prompt Contradiction

Compressed generation prompt currently contains both of these ideas:

- `PC_PHASE` means only the active PC acts, then stop.
- Player action resolution may continue processing remaining NPCs/monsters.

These are incompatible with the human-DM tabletop model.

Required direction:

- `PC_PHASE`: active PC only, no enemy/NPC turns, no next-PC prompt, stop.
- `ENEMY_PHASE`: enemies and allied NPCs batch, PCs are targets only, stop after batch.

### Problem 2: Validator Carries Legacy Full-Round Assumptions

The multi-PC validation prompt still contains old language about processing turns until reaching the `[>]` PC. That is valid for ENEMY_PHASE, but misleading for PC_PHASE.

Required direction:

- Validation must branch by phase.
- PC_PHASE validation should not demand batch flow.
- ENEMY_PHASE validation should remain strict.

### Problem 3: Deterministic Commands Are Fed Back As LLM Work

`/dmg` and missed `/att` produce already-applied system log messages. These are safe mechanical facts, but the combat LLM still receives them and may produce mechanics or validation churn.

Required direction:

- Deterministic commands should produce local narration by default.
- Only optional cinematic mode should call a narration-only LLM.
- Already-applied command facts should be ledger entries, not new instructions to the combat model.

### Problem 4: Prompt Routing Bugs Can Cause Validation Bounce

Known prompt issues to fix during implementation:

- `Spirit Guardians` damage on enemy turn is enemy HP/status mutation and must route to `updateEncounter`, not `updateCharacterInfo`.
- Healing spell guidance must allow immediate spell-slot expenditure while deferring HP healing until the healing roll is supplied.
- Validation should say `at most one updateEncounter when enemy state changes exist`, not `exactly one updateEncounter per response` in all cases.

### Problem 5: Secondary LLM Updaters Add Hidden Latency

Combat responses that omit supported `ops` can trigger prose update LLMs:

- `updates/update_character_info.py` has a deterministic `ops` path, but prose fallback calls another model.
- `updates/update_encounter.py` has deterministic enemy `ops`, but prose fallback calls another model.

Required direction:

- In combat, supported mechanics should use `ops` whenever possible.
- For deterministic commands, Python should avoid update LLMs entirely.

## Proposed Execution Model

### Tier 1: Deterministic Command Narration

Applies to explicit slash commands whose mechanics are already Python-owned.

Initial supported commands:

- `/att <target> <roll> [weapon]`
- `/dmg <amount> [flavor]`
- Death save roll input
- Existing direct state commands such as `/hp` can remain system-only for now

Behavior:

```text
Input command
  -> parse in Python
  -> apply or confirm mechanical result
  -> print [skipTTS] mechanics report
  -> print deterministic DM narration without [skipTTS]
  -> append PC_PHASE event ledger entry
  -> continue loop, no combat LLM
```

This should be controlled by a config flag:

```python
COMBAT_FAST_DETERMINISTIC_NARRATION = True
```

### Tier 1.5: Optional No-Validation Cinematic LLM Narration

This is optional and should not be the first implementation target.

Behavior:

```text
Python applies mechanics
  -> tiny narration-only LLM prompt
  -> no actions allowed
  -> no combat validation
  -> spoken narration only
```

Potential flag:

```python
COMBAT_LLM_MICRO_NARRATION = False
```

Risk:

- Still waits on provider.
- Can hallucinate unless prompt is very tight.
- Adds complexity before proving deterministic templates feel acceptable.

Recommendation:

- Implement deterministic templates first.
- Add micro-narration later as an opt-in canary.

### Tier 2: Structured Natural-Language PC Actions

Applies when the player/facilitator gives enough mechanical facts in natural language.

Examples:

```text
I charge in and attack the sentry with my greatsword, roll 13 with surprise.
I cast Magic Missile at the three goblins, one dart each for 6, 4, and 3 damage.
I retreat to the back of the shield wall and cast Cure Wounds on Vitreol for 6 HP healing.
```

Target behavior:

```text
Natural-language input
  -> classify action type
  -> extract actor, targets, rolls, amounts, spell/resource
  -> if complete and supported, apply deterministic ops
  -> print mechanical report and deterministic narration
  -> append PC_PHASE ledger entry
  -> no full combat LLM
```

Initial supported parser cases:

- Weapon attack with explicit target and d20 roll.
- Weapon damage with explicit target and amount.
- Magic Missile with explicit targets and dart damage values.
- Cure Wounds or direct healing with explicit target and healing amount.
- Movement/retreat/repositioning with no mechanical state mutation.
- Explicit spell slot spend when spell and level are unambiguous.

Fallback to Tier 3 when:

- Targets are ambiguous.
- Spell level is unclear.
- Attack roll or damage roll is missing.
- Enemy or NPC saving throws are required.
- Area effects require multiple saves.
- Reactions, held actions, grapples, shoves, disarms, cover, or advantage/disadvantage are unclear.

### Tier 3: Full Combat LLM

Applies to complex or ambiguous adjudication.

Examples:

- Fireball or other AoE requiring enemy saves.
- Spirit Guardians ongoing turn-start effects.
- Concentration saves.
- Ambiguous narrated melee with no roll.
- Tactical enemy/NPC decisions in ENEMY_PHASE.
- Combat exit and XP flow.

Behavior remains close to current path, but with prompt cleanup and lower PC_PHASE retry pressure.

## Deterministic Narration Design

### Output Channels

Do not collapse mechanical report and narration into one message.

Use two lines:

```text
[skipTTS] Dungeon Master: <mechanical report>
Dungeon Master: <spoken deterministic narration>
```

Why:

- Mechanical report preserves operator trust.
- Narrative line remains immersive in DM Voice.
- TTS does not speak math-heavy report text.
- Debugging remains clear.

### Narration Inputs

The deterministic narrator should use only confirmed fields:

- `actor_name`
- `target_name`
- `weapon_name` or `damage_flavor`
- `attack_roll`
- `target_ac`
- `hit_or_miss`
- `damage_amount`
- `hp_before`
- `hp_after`
- `target_status`
- `target_type`
- optional explicit user flavor from `/dmg`

### Template Families

Templates should be short, varied, ASCII-only, and deterministic enough for tests.

Miss templates:

```text
{actor}'s {weapon} cuts empty air as {target} slips just outside the strike.
{actor} commits to the blow, but {target} twists away before the {weapon} lands.
{target} jerks aside, and {actor}'s {weapon} scrapes harmlessly past.
```

Wound templates:

```text
{actor}'s {weapon} lands hard, driving {target} back with a sharp impact.
{actor} catches {target} cleanly with the {weapon}, forcing it to stagger.
{actor}'s strike bites into {target}, leaving it reeling but still fighting.
```

Bloodied templates:

```text
{actor}'s {weapon} tears into {target}, leaving it staggered and visibly weakened.
{target} reels under {actor}'s blow, its defense breaking for a dangerous moment.
```

Kill/defeat templates:

```text
{actor}'s {weapon} finishes {target}; it collapses in a broken heap.
{actor} drives the final blow home, and {target} drops out of the fight.
{target} buckles under {actor}'s strike and falls still.
```

Healing templates:

```text
Warm light gathers around {actor}'s hands and flows into {target}, steadying their breath.
{actor}'s magic closes the worst of {target}'s wounds, pulling them back from the edge.
```

Movement templates:

```text
{actor} falls back behind the shield wall, trading reach for a safer line.
{actor} shifts position, boots scraping across the floor as the battle line reforms.
```

### Variation Without Randomness Risk

Use deterministic selection based on a stable hash of event fields, not global randomness.

Example seed fields:

- actor
- target
- event kind
- round
- action count in PC_PHASE ledger

This gives varied text while preserving testability.

## PC_PHASE Event Ledger

### Purpose

Create a compact authoritative record of PC_PHASE events that can be reused later for recap or merged round narration without replaying mechanics.

This ledger is not the source of mechanical truth. Character files and encounter files remain authoritative. The ledger is narrative/history metadata.

### Storage Options

Preferred initial location:

- In-memory on `MultiPCCombatManager` for current combat session.
- Persist a compact copy to encounter JSON only if needed for crash/restart continuity.

Potential key:

```json
"pcPhaseEvents": []
```

If persisted, entries must be clearly historical and non-authoritative.

### Event Shape

```json
{
  "event_id": "round2-acheron-003",
  "round": 2,
  "phase": "PC_PHASE",
  "actor": "Acheron",
  "kind": "attack_damage",
  "target": "Skeleton_2",
  "weapon": "axe",
  "attack_roll": 17,
  "target_ac": 14,
  "damage": 8,
  "hp_before": 6,
  "hp_after": 0,
  "status": "dead",
  "mechanics_already_applied": true,
  "narration": "Acheron's axe crashes through the skeleton's ribs, scattering old bones across the flagstones."
}
```

### Supported Event Kinds

Initial set:

- `attack_miss`
- `attack_hit_pending_damage`
- `attack_damage`
- `spell_damage`
- `spell_healing`
- `spell_cast_pending_roll`
- `movement`
- `condition_change`
- `death_save`
- `manual_note`

### Ledger Use At `/end`

When facilitator enters `/end`, pass ledger facts as historical context only:

```text
=== PC PHASE RECAP FACTS (HISTORICAL ONLY; DO NOT REPLAY MECHANICS) ===
- Acheron missed Skeleton_1 with axe, roll 9 vs AC 14.
- Lidda dealt 8 damage to Skeleton_2, HP 6 -> 0, status dead.
- Vitreol moved behind shield wall and healed Acheron for 6 HP.
```

This supports future recap mode and helps ENEMY_PHASE narration acknowledge what happened without reapplying mechanics.

## `/end` Recap And Merged Narration Options

### Mode A: Immediate PC Narration (Recommended First)

```text
PC acts -> deterministic narration immediately
PC acts -> deterministic narration immediately
/end -> enemy LLM batch
```

Benefits:

- Fastest table feedback.
- Low risk.
- No prompt changes needed for historical PC recap initially.
- Each player hears their action result immediately.

Drawback:

- PC phase may feel more templated than LLM prose.

### Mode B: PC_PHASE Recap At `/end`

```text
PC acts -> mechanical report plus brief deterministic line
PC acts -> mechanical report plus brief deterministic line
/end -> LLM narrates PC_PHASE recap from ledger
     -> then ENEMY_PHASE resolves
```

Benefits:

- More cinematic PC-phase summary.
- Lets deterministic per-action narration stay bare bones.

Risks:

- Prompt and validation must distinguish historical PC recap from active PC action.
- Without a strict historical-only contract, validation may reject PC actor narration during ENEMY_PHASE.

Required safeguards:

- Mark recap as `HISTORICAL ONLY`.
- Forbid any PC mechanics actions from recap text.
- Require enemy/NPC mechanics only after recap.
- Add replay guard tests.

Potential flag:

```python
COMBAT_PC_PHASE_RECAP_ON_END = False
```

### Mode C: Merged Cinematic Round

```text
/end -> LLM narrates PC recap and enemy/NPC batch in one response
```

This could be the best eventual UX, especially when PCs win initiative:

```text
The party surges first... [PC recap]
Then the dead answer... [enemy phase]
```

But it should not be implemented first.

Required prerequisites:

- PC_PHASE ledger exists.
- ENEMY_PHASE prompt has explicit recap contract.
- Validator allows historical PC recap but forbids PC mechanics replay.
- Deterministic replay precheck covers both enemy and PC already-applied actions.

Potential flag:

```python
COMBAT_MERGED_PC_AND_ENEMY_NARRATION = False
```

## Natural-Language PC Action Coverage

### Parser Strategy

Use conservative deterministic extraction. If confidence is not high, fall back to current combat LLM.

Do not try to build a full natural-language rules engine in the first pass.

### Supported Case 1: Narrated Weapon Attack With Roll

Input examples:

```text
I charge in and attack the sentry with my greatsword. Roll 13, with surprise.
I slash the goblin with my rapier, 18 to hit.
```

Required extraction:

- actor from active PC/input tag
- target phrase
- weapon phrase
- attack roll
- optional advantage/surprise note

If target resolves and roll/AC are known:

- Apply hit/miss as `/att` would.
- If hit but no damage value, emit hit-pending-damage report and prefill `/dmg`.
- If miss, emit deterministic miss narration.

Fallback when:

- target ambiguous
- no roll supplied
- advantage/surprise needs adjudication and no final roll supplied

### Supported Case 2: Magic Missile With Explicit Dart Damage

Input examples:

```text
I cast Magic Missile at the three goblins, one dart each for 6, 4, and 3 damage.
Magic Missile: two darts into Goblin_1 for 9 total, one into Goblin_2 for 4.
```

Rules:

- No attack roll.
- No save.
- Requires available level 1+ spell slot unless cast source is special.
- Damage to enemies uses `updateEncounter.ops` or direct Python encounter mutation if implemented in deterministic parser.
- Spell slot spend uses `spell_slot_delta` on caster.

Initial implementation options:

1. Parser emits structured actions and runs deterministic update functions.
2. Parser directly mutates Python state through shared helpers.

Preferred direction:

- Reuse deterministic ops helpers where possible, but avoid prose updater LLM.

Fallback when:

- spell slot level unclear and multiple possibilities matter
- target aliases ambiguous
- dart allocation unclear

### Supported Case 3: Cure Wounds With Explicit Healing

Input examples:

```text
I retreat to the back of the shield wall and heal Vitreol with Cure Wounds for 6 HP.
I cast Cure Wounds on Acheron, healing 8.
```

Rules:

- Requires available spell slot.
- Movement can be narrated but does not need a mechanical action unless position tracking is later added.
- Healing target must be PC or allied NPC.
- Healing applies through `updateCharacterInfo.ops` with `hp_delta`, capped by character max HP in existing deterministic ops path if supported.
- Slot spend applies through `spell_slot_delta`.

Fallback when:

- target ambiguous
- healing amount missing
- spell slot unavailable
- target is dead and resurrection rules would be involved

### Supported Case 4: Movement Or Retreat

Input examples:

```text
I retreat behind the shield wall.
I move to cover near the doorway.
```

Initial behavior:

- No mechanical file mutation unless existing position state exists.
- Emit deterministic movement narration.
- Add ledger event kind `movement`.

Future behavior:

- Integrate with spatial map/combat grid when available.

### Supported Case 5: Explicit DM Mechanical Directive

Input examples:

```text
Vitreol takes 6 healing from Cure Wounds.
Apply frightened to Goblin_1 until end of next turn.
Remove prone from Acheron.
```

This is facilitator authority. If explicit, parse and apply when target and condition are supported.

Fallback when:

- unsupported condition duration
- unknown target
- contradiction with death/HP state

## Prompt Cleanup Plan

### Compressed Combat Generation Prompt

Required edits:

- Make `@PHASE_MODEL` the single authority for PC/Enemy phase behavior.
- Change `@PLAYER_ACTION_RESOLUTION.behavior` so PC_PHASE does not continue to NPCs/monsters.
- Fix `@SPIRIT_GUARDIANS` routing to `updateEncounter` for enemy HP mutation.
- Fix healing spell guidance so slot spend and healing deferral can coexist.
- Strengthen `[ALREADY_APPLIED]` guidance: narrate only, do not emit duplicate mechanics.
- Make `ops` required for supported mechanics in combat generation, with prose fallback only for unsupported/ambiguous mechanics.

### Compressed Combat Validation Prompt

Required edits:

- Add phase-specific validation branches.
- PC_PHASE branch: active PC only; no enemy/NPC action requirement.
- ENEMY_PHASE branch: batch all listed enemies and allied NPCs.
- Replace universal `EXACTLY ONE updateEncounter` with `AT MOST ONE updateEncounter when enemy state changes exist`.
- Allow `requestRoll`-only and narration-only already-applied responses as valid PC_PHASE outputs.
- Validate historical PC recap separately if `/end` recap mode is later enabled.

### Uncompressed Prompt Parity

After compressed prompts are fixed:

- Remove or quarantine legacy examples where PCs/allies auto-act through full rounds.
- Remove Unicode and curly punctuation.
- Add a clear note that uncompressed follows compressed runtime authority.
- Update examples to use current human-DM PC_PHASE model.

## Runtime Implementation Phases

### Phase 1: Deterministic Template Narration For Slash Commands

Files likely touched:

- `core/managers/multi_pc_combat.py`
- `core/managers/combat_manager.py`
- `model_config.py`
- `scripts/test_multi_pc_combat.py`
- `scripts/c5_regression_combat.py`

Tasks:

1. Add config flag `COMBAT_FAST_DETERMINISTIC_NARRATION = True`.
2. Add deterministic narration helper for attack miss and damage result.
3. Return three values from command handler or a structured command result object:
   - mechanical feedback
   - optional LLM log message
   - deterministic narration
4. For `/att` miss, print `[skipTTS]` mechanics plus spoken deterministic narration and skip combat LLM.
5. For `/dmg`, print `[skipTTS]` mechanics plus spoken deterministic narration and skip combat LLM.
6. Preserve current behavior behind flag off.
7. Ensure hit-pending-damage `/att` path remains immediate and no-LLM.

Acceptance criteria:

- `/att` hit still prompts `/dmg` without LLM.
- `/att` miss does not call combat LLM when flag on.
- `/dmg` does not call combat LLM when flag on.
- Spoken narration does not include `[skipTTS]`.
- Mechanical report does include `[skipTTS]`.
- Encounter HP/status remains persisted after `/dmg`.

### Phase 2: PC_PHASE Event Ledger

Files likely touched:

- `core/managers/multi_pc_combat.py`
- `core/managers/combat_manager.py`
- possibly `core/managers/combat_state_sync.py`
- tests under `scripts/`

Tasks:

1. Add in-memory PC phase ledger to `MultiPCCombatManager`.
2. Add helper `record_pc_phase_event(...)`.
3. Record deterministic `/att` hit-pending, `/att` miss, `/dmg`, death save, and movement events.
4. Add helper `format_pc_phase_recap_facts()` for prompt injection.
5. Clear or roll over ledger at round boundary and combat end.
6. Decide whether to persist compact historical ledger in encounter JSON for resume support.

Acceptance criteria:

- Ledger records each deterministic command exactly once.
- Ledger marks events as `mechanics_already_applied`.
- Ledger formatting is ASCII-only and compact.
- `/end` can access ledger facts without mutating mechanics.

### Phase 3: Prompt Cleanup And Validation Branching

Files likely touched:

- `prompts/combat/combat_sim_prompt_multipc_compressed.txt`
- `prompts/combat/combat_validation_prompt_multipc_compressed.txt`
- `prompts/combat/combat_sim_prompt_multipc.txt`
- `prompts/combat/combat_validation_prompt_multipc.txt`
- prompt contract tests

Tasks:

1. Remove PC_PHASE contradiction from compressed generation prompt.
2. Fix Spirit Guardians routing.
3. Fix healing slot/deferral wording.
4. Add explicit `[ALREADY_APPLIED]` narration-only rule.
5. Replace universal `exactly one updateEncounter` wording.
6. Mirror changes into uncompressed prompt.
7. Add source-contract tests for these prompt clauses.

Acceptance criteria:

- PC_PHASE prompt says active PC only, then stop.
- ENEMY_PHASE prompt says enemies and allied NPCs only, then stop.
- No prompt says PC_PHASE should continue to enemies/NPCs.
- Spirit Guardians enemy damage routes to `updateEncounter`.
- Healing spell slot spend can coexist with awaiting healing roll.

### Phase 4: PC_PHASE Validation Skip Routes

Files likely touched:

- `core/managers/combat_manager.py`
- `utils/validation_routing.py` or new combat-specific routing helper
- tests under `scripts/`

Tasks:

1. Add deterministic classifier for low-risk PC_PHASE responses.
2. Skip LLM validation when response is `requestRoll`-only and deterministic shape checks pass.
3. Skip LLM validation when response is narration-only and tied to `[ALREADY_APPLIED]` command facts.
4. Skip LLM validation when only supported structured ops exist and deterministic prechecks pass.
5. Keep full validation for ENEMY_PHASE, combat exit, round advancement, and ambiguous responses.

Acceptance criteria:

- Validation telemetry shows skip reasons.
- PC_PHASE requestRoll pauses do not call validation LLM.
- ENEMY_PHASE still calls full validation.
- Exit still receives strict validation.

### Phase 5: Structured Natural-Language PC Action Parser

Files likely touched:

- new helper, possibly `utils/combat_pc_action_parser.py`
- `core/managers/combat_manager.py`
- `core/managers/multi_pc_combat.py`
- tests under `scripts/`

Tasks:

1. Add conservative parser for supported PC action patterns.
2. Implement target resolution through existing combat target helpers.
3. Implement weapon attack with supplied roll.
4. Implement Magic Missile with explicit dart damage.
5. Implement Cure Wounds/direct healing with explicit healing amount.
6. Implement movement-only narration.
7. Fall back to full combat LLM on ambiguity.

Acceptance criteria:

- Supported examples apply without full combat LLM.
- Ambiguous examples fall back safely.
- No enemy/NPC save logic is guessed in Python unless explicitly supported.
- Parser never silently applies uncertain mechanics.

### Phase 6: Optional `/end` PC Recap Mode

Files likely touched:

- `core/managers/combat_manager.py`
- prompts under `prompts/combat/`
- validation prechecks
- tests under `scripts/`

Tasks:

1. Add config flag `COMBAT_PC_PHASE_RECAP_ON_END = False`.
2. Inject ledger facts at `/end` as historical-only context.
3. Add generation prompt clause for PC recap before ENEMY_PHASE.
4. Add validation clause allowing historical PC recap but forbidding PC mechanics replay.
5. Add replay guard tests.

Acceptance criteria:

- PC recap can mention PC actions as history.
- No PC mechanics actions are emitted from recap.
- ENEMY_PHASE mechanics remain enemy/NPC-only.
- Existing `/end` behavior preserved when flag off.

### Phase 7: Optional Micro-Narration LLM

Files likely touched:

- new helper, possibly `utils/combat_micro_narration.py`
- `model_config.py`
- `core/managers/multi_pc_combat.py`
- tests under `scripts/`

Tasks:

1. Add flag `COMBAT_LLM_MICRO_NARRATION = False`.
2. Add small narration-only prompt with no actions allowed.
3. Use deterministic templates as fallback on timeout/error.
4. Do not run combat validation for micro-narration output.
5. Add strict timeout and max token budget.

Acceptance criteria:

- Micro-narration never mutates state.
- If provider stalls/fails, deterministic narration appears immediately or after short timeout.
- No replay actions can be generated because actions are not accepted from this path.

## Test Plan

### Unit Tests

Add/extend tests for:

- Deterministic narration template selection.
- `/att` miss no-LLM path.
- `/dmg` no-LLM path.
- Mechanical report has `[skipTTS]`.
- Spoken narration does not have `[skipTTS]`.
- Ledger event recording.
- Ledger clear/rollover behavior.
- Natural-language parser supported cases.
- Natural-language parser ambiguity fallback.

Likely files:

- `scripts/test_multi_pc_combat.py`
- `scripts/c5_regression_combat.py`
- new `scripts/test_combat_pc_phase_fast_path.py`

### Source Contract Tests

Add tests that lock prompt cleanup:

- PC_PHASE says active PC only and stop.
- ENEMY_PHASE says enemies/allied NPCs batch only.
- Spirit Guardians enemy damage uses `updateEncounter`.
- Healing spell guidance includes spell slot spend plus healing deferral.
- Validation says at most one updateEncounter when enemy state changes exist.
- `[ALREADY_APPLIED]` forbids duplicate mechanics.

### Integration Smoke Tests

Manual or scripted combat smoke:

1. `/att skeleton 9 axe` miss.
2. `/att skeleton 17 axe` hit, then `/dmg 8 axe` kill.
3. Magic Missile explicit dart damage.
4. Cure Wounds explicit healing.
5. Movement-only input.
6. `/end` enemy batch still works.
7. Combat exit still works.

Expected for first implementation pass:

- Cases 1 and 2 avoid full combat LLM.
- Cases 3-5 may still use full combat LLM until Phase 5.
- Case 6 still uses full ENEMY_PHASE LLM and validation.

### Performance Telemetry

Add or reuse telemetry markers:

- `combat_pc_fast_path_used=true`
- `fast_path_kind=attack_miss|attack_damage|healing|spell_damage|movement`
- `combat_llm_skipped=true`
- `validation_llm_skipped=true`
- `pc_phase_ledger_events=<n>`

Goal:

- Compare time from input to visible output before/after.
- Count LLM calls avoided during PC_PHASE.

## Rollout Strategy

### Default Flags

Initial recommended defaults:

```python
COMBAT_FAST_DETERMINISTIC_NARRATION = True
COMBAT_PC_PHASE_RECAP_ON_END = False
COMBAT_MERGED_PC_AND_ENEMY_NARRATION = False
COMBAT_LLM_MICRO_NARRATION = False
```

### Safe Revert

Each feature should be independently disableable.

If deterministic narration feels too bare:

- Keep fast mechanical path.
- Enable `/end` recap experiment.
- Later test micro-narration.

If parser misclassifies natural-language actions:

- Disable parser path.
- Keep slash-command fast path.

## Risks And Mitigations

### Risk: Narration Feels Too Templated

Mitigation:

- Use multiple deterministic templates.
- Use event severity and target status to choose different families.
- Add optional micro-narration only after fast path proves mechanically safe.

### Risk: Players Miss Immediate Cinematic Feedback If Recap Delayed

Mitigation:

- Default to immediate deterministic narration.
- Treat `/end` recap as optional experiment, not baseline.

### Risk: Historical PC Recap Trips ENEMY_PHASE Validation

Mitigation:

- Do not implement recap until ledger and validation contract exist.
- Mark recap as historical-only.
- Add replay guard tests before enabling.

### Risk: Parser Applies Ambiguous Mechanics Incorrectly

Mitigation:

- Parser must be conservative.
- Only apply when all required facts are present and target resolution is unique.
- Fall back to full combat LLM otherwise.

### Risk: State Drift From Direct Python Mutation

Mitigation:

- Reuse existing deterministic update helpers where possible.
- Sync encounter and character state immediately after mutation.
- Record ledger entries as historical metadata, not source of truth.

## Open Decisions

1. Should deterministic spoken narration be enabled by default for `/att` miss and `/dmg`, or behind a UI/debug toggle first?
2. Should PC_PHASE ledger persist to encounter JSON for resume safety, or remain in-memory for the first pass?
3. Should natural-language parser directly mutate state, or emit structured ops through existing update functions?
4. Should `/end` recap be narration-only before ENEMY_PHASE, or merged into the enemy-phase response later?
5. Should micro-narration use the combat model, narrator model, or a cheaper dedicated mini role?

## Recommended First Slice

Implement only this first:

1. `COMBAT_FAST_DETERMINISTIC_NARRATION` flag.
2. Deterministic narration helper for `/att` miss and `/dmg`.
3. No-LLM control flow for `/att` miss and `/dmg` when flag is enabled.
4. Basic PC_PHASE ledger entries for those commands.
5. Regression tests proving no combat LLM path is entered.

This slice is small enough to test at the table and directly answers the core question: does fast deterministic PC narration feel good enough during live tabletop play?

If yes, continue to structured natural-language parser and `/end` recap experiments. If no, keep the mechanics fast path but test optional micro-narration.
