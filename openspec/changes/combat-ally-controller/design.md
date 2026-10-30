# Design

## Context

See `proposal.md` for the motivation and scope. The current encounter contract distinguishes `player`, `enemy`, and `npc`, while `TurnQueueManager.get_remaining_enemies_for_round()` puts all living non-PC actors into one DM-controlled group. `/end` is parsed in `core/combat/commands.py` and advances that group; the legacy DM prompt calls NPCs allies. The deterministic enemy resolver accepts hostile enemies and rejects NPC actors, and the enemy batch orchestrator owns its own plan, narration, and apply stages. The turn-commit change already provides one accepted-input identity, a private manifest, character-first writes, and an encounter-last receipt for `enemy_batch` work.

## Goals / Non-Goals

**Goals:**

- Give active allied NPCs a separate plan and narration batch while honoring the initiative-group order approved for this change.
- Let the model choose from Python-issued attack and tactical-intent options using only ally-scoped perception; preserve deterministic Python defaults and mechanical authority.
- Capture bounded PC directives and prefetch intent orders without adding a planner call at `/end` after the prefetch path has been selected.
- Stage the hostile and ally outcomes of one accepted phase input under the existing receipt-backed commit.
- Keep Python-authored combat chat concise, human-sounding, state-accurate, and in the established Narrator/Dungeon Master voice.

**Non-Goals:**

- PC-to-NPC conversion, absent-player handover, or a separate absent-PC autopilot. A PC already represented as an allied NPC uses this controller.
- Model-controlled ally flight or surrender, DM decisions to flee/extract allies, or changes to side-wide surrender ownership.
- A new position, grid, range, reach, line-of-sight, or movement simulation. Such inputs remain future work; this design does not assume that positionless combat is the final model.
- Changes to hostile enemy menu semantics, legacy prompt bytes, G5T/G5R evidence, or their goldens.

## Decisions

### D1. Treat active encounter `type=npc` entries as the current allied-NPC cohort

The existing schema has no ally/faction field, and the current combat manager explicitly presents encounter NPCs as NPC allies. The controller therefore classifies only encounter entries with `type=npc`, positive HP, and active status as allies. It does not infer alliance from names, prose, character-sheet loyalty, or party size, and it does not add an encounter faction schema in this change. A future character-sheet loyalty input may replace the default, but every current ally defaults to loyal.

**Alternative considered:** Add an ally/faction field to every encounter NPC. Rejected for this change because no existing contract supplies it and the current runtime already treats its combat NPC cohort as allies.

### D2. Use initiative-group order to place the distinct ally batch

Each side-specific cohort keeps initiative order internally. If the DM group wins, execution order is hostile enemies, allied NPCs, then PCs. If the PC group wins, it is PCs, allied NPCs, then hostile enemies. The existing `combat_phase` values remain sufficient: the input/phase orchestrator schedules the ally batch at the between-side boundary rather than introducing a third persisted combat phase. The hostile resolver and prompt retain their current semantics; the controller only supplies the separate NPC batch.

**Alternative considered:** Always run allies before or after enemies, or interleave both cohorts into one plan. Rejected because those choices either contradict the initiative result or remove the required separate ally plan/perception boundary.

### D3. Make the plan a side-specific choice layer, not a second mechanics engine

Build one immutable menu for the scheduled active allies. Each menu option has an opaque ID and a Python-owned interpretation. The current applied menu is limited to options with existing Python legality and effect contracts, including legal attack options and the existing authored `take_cover` option only when its current cover contract permits it. Do not add a new defensive mechanic in this change. The model chooses issued IDs only; missing, illegal, or unavailable choices use the Python rule default. The ally projection contains only that cohort's legal options and facts available to it; it excludes enemy-only plans, hidden facts, full rosters, and unrelated prompts.

**Alternative considered:** Let the model emit actions, positions, targets, or mechanics as free text. Rejected because it would bypass menu legality and Python's mechanical authority.

### D4. Reserve spatial movement and protection intents as placeholders

Movement/protection intents are not current ally-menu options and have no current mechanical or standing-order effect. Reserve the following descriptive placeholders for later grid-mapping work; these names are not stable option IDs or a schema commitment:

| Candidate placeholder | Future Python-owned contract to define |
| --- | --- |
| `move_to_cover` | Actor position, legal path, movement budget, authored cover geometry, and the resulting position/cover state update. |
| `interpose_for_ally` | Actor and ally positions, reach/adjacency, the protected attack trigger, action or reaction cost, and the exact resolved effect. |
| `guard_ally` | Ally position/state, any required adjacency and duration, action cost, and the exact protection effect and end condition. |

Until a later change defines those inputs and effects, Python SHALL NOT offer or apply these placeholders, infer positions from prose, simulate movement, or narrate a positional benefit as though it occurred. The current G5A defensive observation uses only an already-supported legal authored `take_cover` option under its existing Python contract. Future spatial state should extend the same menu-legality seam with Python-owned positions, visibility, range, reach, and movement budgets; it must not accept model-supplied coordinates.

**Alternative considered:** Expose movement/protection placeholders as current intent-only menu options. Rejected because the current planner could appear to execute a tactic without any authoritative position or mechanical effect. The placeholders are documentation only until the grid-mapping change supplies those contracts.

### D5. Parse `/cmd` in Python and coalesce directives per ally

The command handler matches the exact `/cmd` token and resolves the longest normalized active-NPC name prefix, leaving the remaining text as the directive. It strips control characters, normalizes whitespace, rejects empty text, and rejects text longer than 240 characters rather than silently truncating it. It records a bounded typed directive as private metadata on the accepted-input history record; the existing provider-message allowlist excludes that metadata, and the ally projector includes it only for the named actor. The existing pre-commit history write marks the directive consumed with the same manifest that stages the ally batch, so recovery cannot consume it twice. The latest directive per ally replaces earlier directives until the next ally batch. If prefetch is disabled, coalescing continues until that batch. If prefetch is active, directives arriving before the single re-plan request are coalesced into it; after the re-plan request has been submitted, further same-batch `/cmd` input receives a clear rejection and makes no state change. The directive is guidance and expires when that ally batch is committed.

**Alternative considered:** Keep raw command text in the general prompt or allow unbounded directive accumulation. Rejected because it weakens actor isolation and creates unbounded input; silently truncating user guidance was also rejected.

### D6. Prefetch conditional intents with one bounded re-plan

`COMBAT_ALLY_CONTROLLER_ENABLED=False` requires `DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True`; `COMBAT_ALLY_PREFETCH_ENABLED=False` additionally requires the controller flag. During an eligible PC phase, submit one initial immutable ally-order request bound to encounter, ally-batch, and active ally-roster identity. A valid `/cmd` or an applicable major state edge may trigger one re-plan. The background cap is two per ally batch and is accounted separately from synchronous planning. At the between-side boundary, compile the newest usable intent against current menus; if the submitted prefetch path has no usable result, use rule defaults without waiting or making a synchronous planner request. If no prefetch was selected, retain the one synchronous plan path. These flags are enabled only in the isolated G5A sandbox.

**Alternative considered:** Submit a planner request for each PC action or issue a synchronous replacement request at `/end`. Rejected because it increases lag/calls and conflicts with DM-owned phase completion and the bounded request contract.

### D7. Keep the chat response in Python's constrained Narrator voice

Python remains responsible for command parsing and immediate feedback. Use concise bounded reply variants in the existing Narrator/Dungeon Master style; move internal diagnostics to logging rather than chat. Do not add a provider request solely to acknowledge `/cmd`. The separate ally narration request may include a brief in-character reply from the named ally when it matches the accepted ledger. Existing `/att`, `/dmg`, and `/init` mechanical text and behavior remain stable; optional flavor is presentation-only. The chat-voice rule applies to Python-authored combat replies, including `/end`, without changing their mechanics.

**Alternative considered:** Ask the model to decide whether `/cmd` was valid or make a separate call for an immediate acknowledgement. Rejected because command truth is Python-owned and the extra call would add avoidable latency.

### D8. Stage both side batches under the existing accepted-input receipt

The hostile and ally batches remain separate plan/narration/perception units, but their mechanical projections are staged in the initiative-approved order before persistence. One accepted input retains its existing `turn_id` and `applied_id`; the combined final encounter projection, changed-character effects, and narration are written through the existing `path=enemy_batch` manifest/receipt protocol. Commit characters in canonical order, write the encounter once last, synchronize runtime state, then publish the combined Narrator output. Do not create a per-side receipt, direct SQL write, or extra gameplay-state write. This also allows the second side's menu to be built from the first side's staged outcome.

**Alternative considered:** Commit hostile and ally outcomes separately. Rejected because it would create two receipt boundaries for one accepted input and leave a partial phase if a process stopped between them.

## Risks / Trade-offs

- **The initiative-ordered side batches change the sequencing for encounters with allied NPCs when the controller is enabled** -> Freeze the two approved group orders in provider-free tests and G5A; keep flags off by default and preserve hostile-only G5T/G5R contracts.
- **Prefetch can be pending, invalid, or stale when the between-side boundary is reached** -> Never wait or make a synchronous repair request after selection; apply the rule-based defaults and report bounded outcomes.
- **A directive can contain adversarial or excessive text** -> Resolve the target in Python, normalize and cap the text, scope it to one actor, and expose only that bounded directive in the ally projection.
- **A voice response could claim an effect not applied by Python** -> Generate bounded feedback from parser/ledger outcomes and validate the narrated ally result against the committed ledger.
- **Future movement/protection intents need spatial state and explicit mechanics** -> Keep their placeholders out of current menus and prefetch schemas; do not infer movement or add effects through narration.

## Migration Plan

1. Add provider-free tests for active ally selection, menus, actor-scoped projection, loyal defaults, and the rule fallback before connecting the planner.
2. Add `/cmd` parsing, bounded history metadata, Narrator-voice feedback, directive coalescing, and provider-free command/prefetch lifecycle tests.
3. Add the two initiative orderings and separate ally plan/narration path; stage side outcomes and verify one existing receipt commit for 1-PC and 4-PC parties.
4. Add G5A selectors, fixtures, offline report checks, and byte-identical compatibility guards. Keep controller flags false outside the sandbox.
5. After provider-free checks pass, the primary orchestrator runs six isolated live G5A captures and records the verdict. Builders do not run the capture or claim its verdict.

### Rollback

Set `COMBAT_ALLY_CONTROLLER_ENABLED=False` and `COMBAT_ALLY_PREFETCH_ENABLED=False` to return combat planning to the existing path. Preserve any already committed turn receipt and manifest; do not roll back a partial commit. If voice formatting is separately rolled back, retain Python-owned command parsing, mechanics, and state behavior.

### Forward compatibility: V2 spatial combat

- Python-built menu legality remains the attachment point for future range, reach, line-of-sight, cover, and movement-budget checks.
- Actor-scoped perception may grow to include Python-owned positions and what each ally can observe; positions and geometry remain Python authority.
- Prefetched tactical intents remain conditional preferences and must be compiled against the current spatial menu when position state exists; position changes then become explicit re-plan/freshness inputs.
- G5A and existing G1/G3/G4/G5R/G5T evidence remain positionless compatibility contracts. Spatial combat requires new scenarios and gates rather than rewriting those goldens.
