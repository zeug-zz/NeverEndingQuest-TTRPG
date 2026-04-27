# Narration Reality - Death, Supernatural Continuity, and Python Authority

## Status

- Draft for review
- Scope: tabletop runtime narration-state boundary hardening
- Motivation: preserve flexible DM narration while preventing silent mechanical contradiction
- Current live trigger case: Vitreol death, corrupted-thrall narration, location transition drift, and long-rest accidental resurrection

## Objective

Preserve the strength of NeverEndingQuest's LLM DM: vivid, adaptive, surprising narration that can interpret strange table events creatively. At the same time, make sure Python remains the durable source of mechanical truth for PC death, resurrection, location presence, rest recovery, and persistent world state.

The goal is not to stop the narrator from saying something like:

```text
Vitreol is dead, but something wearing Vitreol's shape opens its eyes.
```

The goal is to stop the runtime from silently converting that into:

```text
Vitreol took a normal long rest and is fine now.
```

## Prime Directive

Python enforces reality; the DM interprets it.

This means:

1. Python owns objective mechanical state: HP, dead/alive status, death saves, rest effects, location, party membership, combatant state, and persistent NPC/scene-entity presence.
2. The DM owns subjective interpretation: dreams, omens, possession, corruption, mistaken identity, spiritual echoes, bargains, visions, and consequences.
3. If the DM narration creates a durable new fact, it must be represented in Python state through an explicit action or state-shape choice.
4. If no state action is emitted, the narration remains flavor, memory, foreshadowing, or subjective experience.

## Current Incident Summary

The live Vitreol incident exposed several interacting problems:

1. Vitreol was mechanically dead in a backup state:
   - `status: dead`
   - `hitPoints: 0`
   - `deathSaves.failures: 3`
2. The narrator later insisted Vitreol was merely unconscious at 0 HP.
3. Acheron's altar ritual produced excellent emergent narration: a corrupted Vitreol-like thrall or vessel appeared.
4. That state was stored as a location-bound scene anchor, `vitreol_thrall`, at NC02.
5. The party later transitioned to NC04, leaving the scene anchor behind.
6. Long-rest automation treated PC Vitreol like a living character and restored her to full HP/alive state.
7. A later player prompt caused the narrator to mention Vitreol at NC04, which collided with the NC02 `vitreol_thrall` anchor because that anchor had bare alias `Vitreol`.
8. The location exclusivity guard correctly blocked an off-location scene anchor from being instantiated at NC04, but the deeper issue was unresolved identity and state shape.

## Design Tension

The narrator was doing something valuable. It turned death and corruption into interesting gameplay instead of a flat failure state. The system should support that.

The problem was not that the narrator invented a supernatural interpretation. The problem was that the runtime never forced the narration to choose a durable mechanical shape.

The system needs to support four different valid outcomes:

1. The PC remains dead, and the thrall is a separate NPC or scene entity.
2. The PC becomes a corrupted undead PC through an explicit resurrection/corruption mechanic.
3. The apparent thrall is only a vision, dream, echo, or foreshadowing.
4. A dead PC is revived by a real resurrection effect, with explicit state changes and consequences.

All four are valid story outcomes. They must not collapse into accidental normal healing.

## Core State Shapes

### Shape A: Dead PC Remains Dead

Use when the player character has died and no resurrection effect has completed.

Mechanical state:

```json
{
  "name": "Vitreol",
  "status": "dead",
  "hitPoints": 0,
  "deathSaves": {"successes": 0, "failures": 3},
  "condition": "none",
  "condition_affected": []
}
```

Narration may include:

- grief
- carrying the body
- attempted resurrection
- spiritual visions
- corruption attempting to claim the body
- NPCs reacting to the corpse

Narration must not imply normal rest or healing restores the PC.

### Shape B: Dead PC Plus Separate Thrall Entity

Use when something resembling the PC appears, but the original PC is still dead.

Mechanical state:

- PC Vitreol remains `status: dead`.
- A separate entity exists, for example `vitreol_thrall`.
- That entity must have one of these persistence modes:
  - location-bound scene anchor
  - background NPC
  - party-following NPC/companion
  - combatant
  - dream/vision-only non-entity

Valid narration:

```text
The body remains cold in Blairen's arms, but a thing with Vitreol's face rises from the altar smoke.
```

Invalid mechanical collapse:

```text
Vitreol is alive because the thrall spoke.
```

### Shape C: Corrupted/Undead PC Resurrection

Use when the PC really returns as the same playable character, but changed.

Mechanical state must include an explicit transition:

- `status` changes from `dead` to `alive` or a future explicit `undead`/`corrupted` lifecycle state.
- `hitPoints` becomes a deliberate value, not a rest side effect.
- `deathSaves` reset only because resurrection explicitly occurred.
- persistent corruption metadata is written somewhere durable.

Possible future additive fields:

```json
{
  "status": "alive",
  "hitPoints": 1,
  "deathSaves": {"successes": 0, "failures": 0},
  "_tabletop_role_history": [
    {
      "event": "resurrected_corrupted",
      "source": "voidstone_altar",
      "locationId": "NC04"
    }
  ],
  "supernatural_state": {
    "kind": "corrupted_resurrection",
    "source": "Voidstone altar",
    "narrative_flags": ["hunger", "void-dreams", "uncertain_soul_anchor"]
  }
}
```

This should require explicit action routing. It must not happen through generic HP restoration.

### Shape D: Dream, Vision, Echo, or Foreshadowing

Use when the narrator wants symbolic flexibility without committing world state.

Mechanical state:

- no PC status change
- no NPC movement
- no scene anchor instantiated at the current location

Valid narration:

```text
The dream clings to Vitreol, and somewhere far behind you the grove seems to remember her shape.
```

The location exclusivity guard should allow this if phrased as dream, memory, or foreshadowing.

## Problems To Fix

### Problem 1: Dead PCs Are Not Sticky

Current behavior allows positive HP to clear explicit death and reset death saves.

Known risky paths:

- `utils/character_state_hygiene.py::normalize_life_state_fields()`
- `updates/update_character_info.py::_sync_death_save_state()`
- `utils/pc_manager.py` character load normalization
- `core/managers/combat_manager.py` prompt normalization
- rest automation through `_process_character_rest()`

Required behavior:

- `status: dead` is authoritative.
- `deathSaves.failures >= 3` is authoritative.
- Generic healing, rest, repair, and positive HP writes cannot clear death.
- Dead PCs keep `hitPoints: 0` unless a dedicated resurrection path runs.

### Problem 2: Long Rest Can Accidentally Resurrect Dead PCs

Current long-rest automation restores HP, slots, features, and removes exhaustion for all target party members.

Required behavior:

- Dead characters do not benefit from ordinary short or long rests.
- Dead characters remain dead and at 0 HP after rest.
- Rest summary can include a clear skipped marker.
- Resurrection or undeath must be a separate explicit action/state transition.

### Problem 3: DM Note Under-Reports Death

Current PC DM-note formatting emphasizes HP and conditions but does not clearly display `status: dead` or death-save failures.

Required behavior:

- Full PC stats must include status.
- Condensed PC stats must include status when abnormal.
- Dead/downed PCs must show death saves.
- Dead status must be phrased as mechanical truth, not flavor.

Example:

```text
Status: DEAD [MECHANICAL TRUTH]
Death Saves: 0 success / 3 failure [DEAD]
```

### Problem 4: Scene Anchors Can Collide With Party Member Names

The `vitreol_thrall` anchor had aliases including bare `Vitreol`. When the current party member Vitreol was present at NC04, the exclusivity guard treated that as possible off-location instantiation of the NC02 anchor.

Required behavior:

- Bare party-member name aliases should not by themselves trigger off-location scene-anchor violations.
- Distinctive scene-state aliases must still trigger violations.
- `corrupted Vitreol`, `Voidstone thrall`, and `vitreol_thrall` should remain protected scene-anchor aliases.

This preserves both:

- PC Vitreol can be present where the party is.
- The NC02 corrupted thrall cannot physically appear at NC04 unless moved or transitioned.

### Problem 5: Scene Entities That Follow The Party Need State Movement

If a supernatural entity starts as a location-bound scene anchor but then follows the party, the narrator must emit or trigger a state change.

Required behavior:

- A location-bound scene anchor remains at its authored location.
- If it follows, it must become a background NPC, party NPC, companion, or explicit carried/following scene entity.
- Location transition code should know whether it accompanies the party.

### Problem 6: Resurrection Is Not A First-Class Runtime Concept

There is no dedicated resurrection/corruption action path. That leaves the narrator to use generic HP/status updates, which are too ambiguous and too dangerous.

Required behavior:

- Add or design a dedicated resurrection/corruption state transition path.
- It should be explicit, auditable, and narrow.
- It should support normal resurrection and supernatural altered returns.

## Implementation Plan

### Phase 1: Mechanical Death Stickiness

Goal: make accidental resurrection impossible.

Files:

- `utils/character_state_hygiene.py`
- `updates/update_character_info.py`
- `scripts/test_character_state_hygiene.py`
- likely `scripts/test_update_character_ops_contract.py` or a new focused test

Tasks:

1. Add a helper such as `is_mechanically_dead(character_data)`.
2. Treat these as dead:
   - `status == "dead"`
   - `deathSaves.failures >= 3`
3. In `normalize_life_state_fields()`:
   - if mechanically dead, force `status = "dead"`
   - force `hitPoints = 0`
   - preserve or normalize `deathSaves.failures = max(existing, 3)`
   - clear `unconscious` from conditions
   - do not reset death saves due to positive HP
4. In `_sync_death_save_state()`:
   - apply the same mechanically dead check before the `current_hp > 0` branch
   - force dead state and return early
5. Add tests for:
   - positive HP cannot revive `status: dead`
   - `deathSaves.failures: 3` forces `status: dead`
   - dead characters do not retain `unconscious` condition
   - alive positive HP still clears stale unconscious as before

Acceptance criteria:

- A dead PC cannot become alive through generic HP normalization.
- Existing positive-HP stale-unconscious repair still works for non-dead PCs.
- Tests prove both sides of the boundary.

### Phase 2: Rest Skips Dead Characters

Goal: ordinary rest does not resurrect the dead.

Files:

- `core/ai/action_handler.py`
- `scripts/test_rest_action.py`

Tasks:

1. Add a dead-character guard near the start of `_process_character_rest()` after character load.
2. If dead:
   - do not restore HP
   - do not restore spell slots
   - do not refresh class features
   - do not remove exhaustion through rest
   - do not call `update_character_info()` with rest changes
3. Return a structured result such as:

```python
{
    "character": character_name,
    "rest_type": rest_type,
    "skipped": True,
    "skip_reason": "dead",
    "actions": ["No ordinary rest benefit: character is dead"]
}
```

4. Ensure rest summary reports the skip without implying resurrection.
5. Add a dead-character long-rest regression using a temp character file.

Acceptance criteria:

- Dead PC remains `status: dead`, `hitPoints: 0`, `deathSaves.failures: 3` after long rest.
- Alive long-rest behavior remains unchanged.
- Rest remains fail-open for journal checkpoint degradation.

### Phase 3: DM Note Death Visibility

Goal: make mechanical death impossible for the narrator to miss.

Files:

- `utils/multi_pc_dm_note.py`
- existing or new focused tests/source guards

Tasks:

1. Add `Status:` output to `format_pc_full_stats()`.
2. Add compact abnormal status output to `format_pc_condensed()`.
3. Add death-save output when:
   - status is dead
   - HP is 0
   - death-save successes/failures are non-zero
4. Use high-signal wording for dead state.

Suggested full format:

```text
Status: DEAD [MECHANICAL TRUTH]
Death Saves: 0 success / 3 failure [DEAD]
```

Suggested condensed format:

```text
Status: DEAD; Death Saves: 0S/3F
```

Acceptance criteria:

- Active dead PC DM note explicitly says dead.
- Non-active dead PC condensed note explicitly says dead.
- Normal alive PCs do not get noisy extra text beyond `Status: alive` if that is considered too verbose.

### Phase 4: Scene-Anchor Alias Collision Hardening

Goal: preserve scene-anchor protection without mistaking current party members for off-location anchors.

Files:

- `utils/narrator_location_exclusivity_guard.py`
- `main.py`
- `scripts/test_narrator_location_exclusivity_guards.py`

Tasks:

1. Extend `evaluate_location_exclusivity_decision()` with an optional parameter:

```python
party_member_names: Optional[List[str]] = None
```

2. In `main.py`, pass `party_tracker_data.get("partyMembers", [])`.
3. Add canonical identity matching for bare aliases:
   - lowercase
   - spaces/underscores equivalent
   - punctuation removed
4. If an off-location anchor alias exactly matches a current party member name, ignore that specific alias for exclusivity matching.
5. Do not ignore longer/distinctive aliases that include extra state language.

Examples:

- Ignore: `Vitreol` when `Vitreol` is a current party member.
- Block: `corrupted Vitreol` if the corrupted anchor belongs to another location.
- Block: `Voidstone thrall` if it belongs to another location.
- Block: `vitreol_thrall` if it belongs to another location.

Acceptance criteria:

- PC Vitreol can speak and act at current party location.
- NC02 `vitreol_thrall` cannot appear physically at NC04 unless moved.
- Existing location exclusivity tests still pass.

### Phase 5: Supernatural State-Shape Contract

Goal: let the narrator keep doing strange, excellent things, but require explicit state shape when durable.

Files likely involved:

- `prompts/system_prompt_compressed.txt`
- `prompts/system_prompt.txt`
- validation prompts if needed
- possibly `core/ai/action_handler.py`
- possibly `utils/scene_entity_contract.py`

Tasks:

1. Add prompt guidance for dead-PC supernatural narration.
2. Define valid state-shape choices:
   - dead PC remains dead
   - separate NPC/scene entity appears
   - resurrected/corrupted PC returns
   - dream/vision/foreshadow only
3. Require actions for durable changes:
   - PC resurrection/corruption needs explicit character update or future dedicated action.
   - separate entity following party needs `moveBackgroundNPC`, `updatePartyNPCs`, or future scene-entity movement action.
   - dream/vision needs no action but must avoid present-scene physical claims.
4. Add validator language to reject narration that changes durable state without an action.

Suggested compressed prompt concept:

```text
@DEATH_AND_SUPERNATURAL_STATE={
  truth: "PC death in DM Note is mechanical truth. Ordinary healing/rest cannot reverse it.",
  freedom: "You may narrate visions, echoes, corruption, possession, or things wearing a dead PC's shape.",
  requirement: "If the effect is physically present or durable, choose a state shape and emit matching action.",
  shapes: "dead_pc_only | separate_entity | corrupted_resurrection | dream_or_vision",
  no_silent_revival: "Never convert dead PC to alive via rest or ordinary HP narration."
}
```

Acceptance criteria:

- The narrator can produce corrupted-thrall gameplay.
- The narrator cannot accidentally resurrect a dead PC without explicit state transition.
- Validator feedback tells the narrator what state-shape action is missing.

### Phase 6: First-Class Resurrection and Corruption Action

Goal: support deliberate, auditable resurrection and altered returns.

This phase can be deferred until after the safety fixes.

Possible approaches:

1. Add a new action: `resurrectCharacter`.
2. Add structured ops under `updateCharacterInfo`, such as:
   - `resurrection_apply`
   - `set_supernatural_state`
   - `clear_death_saves_for_resurrection`
3. Add a dedicated helper in `updates/update_character_info.py` that only clears death when the op explicitly indicates resurrection.

Potential payload:

```json
{
  "action": "resurrectCharacter",
  "parameters": {
    "character": "Vitreol",
    "mode": "corrupted_resurrection",
    "hitPoints": 1,
    "source": "Voidstone altar",
    "consequences": ["void hunger", "dreams of foul water", "uncertain soul anchor"]
  }
}
```

Validation rules:

- source must be present
- mode must be explicit
- HP must be bounded
- death saves reset only inside this path
- ordinary `hitPoints` edits cannot do this

Acceptance criteria:

- Real resurrection is possible.
- Corrupted/undead return is possible.
- Accidental generic healing remains blocked.

### Phase 7: Following Scene Entities

Goal: make entities like `vitreol_thrall` able to travel if the story says they travel.

Possible state model:

```json
{
  "scene_followers": [
    {
      "anchorId": "vitreol_thrall",
      "displayName": "Vitreol's corrupted echo",
      "originLocationId": "NC02",
      "currentLocationId": "NC04",
      "followsParty": true,
      "entityType": "sceneEntity",
      "combatValid": false
    }
  ]
}
```

Alternative: promote the scene anchor to `partyNPCs` or background NPC when it begins following.

Tasks:

1. Decide whether following scene entities belong in `party_tracker.json`, location memory, or a dedicated scene-entity state file.
2. Add a movement/update action for scene entities.
3. Teach location exclusivity guard to treat moved/following scene entities as present at current location.
4. Keep combat validity separate from scene presence.

Acceptance criteria:

- A scene entity can follow the party without causing off-location violations.
- Location-bound anchors remain protected when not moved.
- Scene-only entities do not become combatants unless explicitly escalated.

## Current Runtime Data Repair Plan

This should be done after Phase 1 and Phase 2 code safeguards, unless urgent live play repair is needed sooner.

Vitreol current repaired target depends on table decision.

### Option 1: Restore PC Vitreol As Dead

Use if the table wants to preserve the original mechanical death.

Set `characters/vitreol.json` to:

```json
{
  "status": "dead",
  "hitPoints": 0,
  "deathSaves": {"successes": 0, "failures": 3},
  "condition": "none",
  "condition_affected": []
}
```

Use backup reference:

```text
characters/vitreol.backup_update_20260425_182332.json
```

### Option 2: Canonize Corrupted Resurrection

Use if the table prefers the emergent result: Vitreol returned wrong.

Apply an explicit state transition once the resurrection/corruption path exists:

- `status: alive` or future supernatural status
- intentional HP value
- death saves reset by resurrection, not rest
- supernatural/corruption metadata recorded
- diary/journal note created if appropriate

### Option 3: Split PC And Thrall

Use if the table wants PC Vitreol dead but a Vitreol-shaped entity active.

- PC Vitreol remains dead.
- `vitreol_thrall` becomes a separate scene entity, NPC, or companion.
- If it follows the party, persist movement/following state.

## Testing Plan

Run focused tests after each phase.

Suggested commands:

```bash
.venv/bin/python scripts/test_character_state_hygiene.py
.venv/bin/python scripts/test_rest_action.py
.venv/bin/python scripts/test_narrator_location_exclusivity_guards.py
```

Additional likely checks:

```bash
.venv/bin/python -m py_compile utils/character_state_hygiene.py updates/update_character_info.py core/ai/action_handler.py utils/multi_pc_dm_note.py utils/narrator_location_exclusivity_guard.py main.py
```

If prompt files change, run relevant narrator validation/source-guard suites:

```bash
.venv/bin/python scripts/test_narrator_prompt_validation_refactor.py
.venv/bin/python scripts/test_retry_de_looping.py
```

## OpenSpec Recommendation

This plan should likely become a chain of small OpenSpec changes rather than one large implementation.

Suggested changes:

1. `tt-dead-pc-mechanical-stickiness`
   - Phases 1-3
   - lowest risk and highest urgency
2. `tt-scene-anchor-party-identity-collision`
   - Phase 4
   - fixes current validation loop class
3. `tt-supernatural-state-shape-contract`
   - Phase 5
   - prompt/validator contract for DM freedom with Python grounding
4. `tt-resurrection-and-corruption-state-action`
   - Phase 6
   - explicit resurrection/corrupted return mechanic
5. `tt-following-scene-entity-state`
   - Phase 7
   - durable movement for scene entities that accompany the party

## Non-Goals

Do not make the narrator timid.

Do not reject all weird death narration.

Do not require every dream, omen, or hallucination to become Python state.

Do not remove scene-anchor exclusivity protections.

Do not make ordinary healing/rest able to resurrect dead PCs.

## Desired End State

NEQ should support nuanced moments like:

```text
Vitreol wakes hungry and laughing, but the DM Note says Vitreol is dead.
Therefore the narrator must decide: is this a dream, a false Vitreol, a corrupted resurrection, or a miracle?
If it is real and durable, Python state must change explicitly.
If Python state does not change, the narration remains subjective or symbolic.
```

That is the core gameplay boundary: maximum narrative flexibility, no silent mechanical lies.
