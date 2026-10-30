# G5 before-reference validator diagnosis

Scope: read-only diagnosis of the two P1 before bundles. No runtime, capture, or provider calls were made. The before bundles remain failed evidence, not usable passing references.

## Q1. Why did both /end batches fail all five attempts?

Primary cause: validation context assembly omits the authoritative current phase/turn window that the combat prompt gives the main model. `validate_combat_response` builds `phase_state` from the live manager and recognizes exact `Enemies turn.` plus ENEMY_PHASE plus pending enemies as full-batch intent (`core/combat/validation.py:111-128`). That state is used for the deterministic precheck, but is not serialized into `validation_conversation`. The validator instead gets its fixed prompt, a six-exchange history tail, committed combatant truth, encounter JSON, current input, and the candidate (`core/combat/validation.py:288-321,362-419`). The committed truth pack is real, but it does not carry live phase/current-actor state.

The asymmetry is visible in the main prompt path: it renders the deterministic tracker and turn window (`core/combat/prompts.py:539-559,627-633`) and the live phase/pending-enemy block (`core/combat/prompts.py:696-725`). Both server logs record `Extracted turn window: ['Goblin']` (run 1: `server.log:361-362`; run 2: `server.log:412-413`) and the exact `Enemies turn.` input (run 1: `server.log:371`; run 2: `server.log:422`). The validator nevertheless initially says Acheron has not acted / Goblin is not due (run 1: `server.log:401`; run 2: `server.log:452`). Later feedback changes its premise; the validator can then reject for other reasons. This is consistent with missing authoritative validator context, not a failed phase precheck.

Retries amplify the gap: the outer retry stage appends prior validation feedback to the next model request (`core/combat/turn.py:761-774`), then places the new candidate in the history passed to validation (`core/combat/turn.py:845-847`). Validation takes the recent tail (`core/combat/validation.py:298-305`). Thus an incorrect correction can become apparent evidence on the next attempt. The five attempts are the outer generation/validation ladder, not the inner JSON-parse retry (`core/combat/turn.py:761-764,924-961`; `core/combat/validation.py:445-529`).

The failure is not one identical validation rule repeated five times. Run 1's feedback moves from initiative/turn-window rejection through missing prompt/round narration to an attack-count complaint (`server.log:401,468,535,602,669`). Run 2's final response is also independently bad: it narrates Acheron starting Round 2 when that was not allowed (`server.log:720`). Both end in "Using last response" (`server.log:700-701` and `server.log:751-752`); trace records show validation rejected and the resulting batch was not accepted (`trace.jsonl:49,52,55` and `trace.jsonl:53,56,59`).

## Q2. Did deterministic /att or /dmg history/ledger writes fail?

No evidence of a command or mechanical write failure. Both transcripts show `/att Goblin 20 training blade` then `/dmg 1 round 1` (`transcript.log:11-19`). In both bundles Goblin HP is 20 before step 2 and 19 after it (`snapshots/step-002-before.json:67`; `snapshots/step-002-after.json:67`). The hit path records `attack_hit_pending_damage` before returning (`core/combat/multi_pc/manager.py:773-798`); `/dmg` updates enemy HP in encounter data and records `attack_damage` (`core/combat/multi_pc/manager.py:916-924,941-969`). The manager appends these events to its PC-phase ledger (`core/combat/multi_pc/manager.py:551-553`).

The distinction is write versus projection: the ledger exists, but the validator message assembly does not serialize it (`core/combat/multi_pc/manager.py:564-581` versus `core/combat/validation.py:288-419`). The G5 traces contain one deterministic command decision per run, corresponding by timestamp to step 2 `/dmg`, and no separate hit `/att` decision (`trace.jsonl:21` and `trace.jsonl:25`; `transcript.log:11-19`). The missing `/att` trace is an observability gap, not the reason validation failed.

## Q3. Was the enemy-batch prompt missing, or is there a Goblin fixture mismatch?

The main DM prompt was not missing the batch state: it includes turn-window and live pending-enemy data as above. The validator's separate payload is the gap. Its static contract says to process every actor when `turn_window` is present (`prompts/combat/combat_validation_prompt_multipc_compressed.txt:153-160`), but its current user input is only `Enemies turn.` and the validator assembly does not append the main prompt's live window.

There is also a separate, concrete attack-pool defect in the run-1 last attempt. Its validator complains that the pool has two attacks (`server.log:669-673`). The Goblin source has Scimitar and Shortbow action entries, but no Multiattack action (`tmp/combat_capture/modules/Capture_Arena/monsters/goblin.json:32-55`). `get_monster_attacks` returns the count of qualifying action entries (`core/generators/generate_prerolls.py:86-103`), and preroll generation creates that many rolls (`core/generators/generate_prerolls.py:221-232,252-268`); the captured encounter pool indeed says two attacks (`tmp/combat_capture/modules/encounters/encounter_capture_one_pc.json:46-49`). This confuses selectable attack actions with attacks in one turn. It explains that run-1 rejection, not the earlier contradictory feedback in both runs.

## Q4. How does this overlap the planned group-3 work?

- **3.4 validation routing / two-attempt cap:** partial operational overlap only. It could reduce retry cost, but an enemy batch containing narrative and enemy/character updates is not a safe deterministic-only response to skip. A cap cannot supply missing phase facts or guarantee a valid candidate.
- **3.7 retry tier:** may change reasoning effort; it does not restore authoritative phase context and is not a correctness fix.
- **3.2 compression and 3.3 dump gating:** hot-path cost and I/O work only; neither addresses the validation contradiction or attack-count defect.

Smallest correctness follow-up: add a bounded, explicitly authoritative phase block to the validator's existing runtime message assembly (source only from the manager: phase, pending actors/current actor, round, and full-batch intent); keep it separate from candidate claims and keep LLM validation enabled. Separately, correct the preroll attack-count source or make the Capture_Arena fixture explicitly specify one attack for this Goblin. Do not mask the latter by changing validator acceptance.

This phase block changes the validator's effective prompt payload. The active design says no prompt edits and preserves prompt equivalence (`design.md:24-33`); the existing task list does not authorize this context change. Planner/owner approval or a scoped OpenSpec amendment is needed before implementing it. The report itself makes no such change.

Provider-free regression proposal: extend `scripts/test_combat_validation_stage.py` with a captured-LMM-payload assertion for an ENEMY_PHASE manager with pending `Goblin` and exact `Enemies turn.` input. Assert the authoritative block is present, candidate phase claims cannot override it, and the provider validator still runs (no broad enemy-batch skip). Add a separate preroll test asserting the one-action Goblin fixture does not produce two attack rolls absent explicit multiattack/count metadata. Guard with the planned `scripts.test_combat_latency_hot_path.TestValidationRouting`, `scripts.test_combat_phase_integrity_precheck`, `scripts.test_combat_runtime_prompt_authority`, `scripts.test_multi_pc_combat`, `scripts.test_combat_resume_replay_guards`, and `scripts.c5_regression_combat` suites, each in its own process as the task contract specifies.

## Q5. Where should the missing /att decision trace be emitted?

In `core/combat/multi_pc/manager.py::handle_combat_command`, the hit branch records its ledger event and returns at lines 773-798 before any `trace_decision` call. The miss branch traces at lines 843-865, and `/dmg` traces at lines 971-993. Emit the matching deterministic `combat_command_fast_path` decision immediately before the hit-branch return at line 793, after the target/roll is resolved and hit event recorded; use `provider_call_avoided=True`, matching `/dmg`. The observed hit path returns `SkipLLM=True`, so this reports existing behavior without changing routing.

## Assessment

- **High confidence:** validator context omission plus retry-feedback contamination is the common root mechanism. The deterministic command writes and phase precheck were not the failure.
- **High confidence:** `/att` hit decision tracing is missing at the stated return site.
- **Medium-high confidence:** the generated two-attack Goblin pool is a separate run-1 false blocker. Run 2 also has a genuinely invalid final-round narration, so the context correction alone cannot guarantee both captures pass.
- **Planner status:** both P1 before captures remain failed/blocked; do not use them as passing references or begin group 3 until the prerequisite issue is resolved and the planner decides whether to amend scope.

Scratch paths created: none. All `tmp/` artifacts cited above were read-only.
