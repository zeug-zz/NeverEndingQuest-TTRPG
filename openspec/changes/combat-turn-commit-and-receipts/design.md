# Design

## Context

The validated-response path currently updates round/phase state before narration, applies encounter actions immediately, completes opening-phase work, and writes queued character updates later. Atomic writes protect individual JSON files, not the character/encounter set. G7 deliberately changes this legacy ordering; the existing resume replay guards remain in force. See `proposal.md` and the three delta specs for the contract.

The loop-entry `turn_start` trace in `core/combat/turn.py` is emitted before input is read. It remains start telemetry, not a success publication. The current phase helpers also persist encounter changes; this design stages their final persisted snapshot into the encounter-last commit and reserves post-commit phase work for synchronizing runtime managers and queues.

## Goals / Non-Goals

**Goals:**

- Give each accepted input a durable, restart-stable identity before its first mechanical write.
- Commit changed character records before one atomic encounter write containing the receipt and final round/phase snapshot.
- Recover partial character writes and completed commits without duplicating mechanical or reward effects.
- Preserve prompt bytes, current public APIs, the existing replay guards, and one-PC/multi-PC behavior.

**Non-Goals:**

- Replace combat mechanics, provider policy, prompt content, or capture infrastructure.
- Change `MULTIPLAYER_MODE`, add party-size gates, or claim the primary-owned G7 verdict.
- Provide a multi-file filesystem transaction or exactly-once delivery from an external event transport.

## Ten-Line Design Summary

1. Assign a UUID `turn_id` to each accepted input and persist it with that input before mechanical writes.
2. Derive `applied_id` as `sha256:` plus SHA-256 of the specified versioned encounter/turn identity string.
3. Stage validated character, encounter, reward, round, phase, and narration effects; persist their bounded manifest in the existing pre-commit history write.
4. Atomically persist each changed character in stable identity order with `last_combat_applied_id`, skipping matching markers during recovery.
5. Atomically persist the final encounter projection and one exact-schema receipt after all missing character writes.
6. Include the code-derived round and final phase markers in that encounter projection.
7. After the encounter write succeeds, synchronize managers and queues from the committed phase snapshot without another gameplay-state write.
8. Publish success/narration only after synchronization and internally correlate it with the committed `applied_id`; recovery publishes the stored narration.
9. On bootstrap, complete the newest pending history manifest without provider work; skip matching character markers and treat matching receipts as complete.
10. Keep fault injection default-off and sandbox-only; the primary orchestrator alone judges live G7.

## Decisions

### D1. Persist turn identity before effects; derive the applied ID from it

Assign a UUID string as `turn_id` when the accepted user-input history record is created. Persist that metadata before any mechanical write. Compute `applied_id` as `sha256:` plus lowercase SHA-256 hex over UTF-8 bytes of `neq.combat.turn.applied-id.v1\0{encounter_id}\0{turn_id}`. Prompt assembly MUST omit the metadata so existing prompt serialization remains byte-identical.

Alternative considered: reuse `session.begin_turn_iteration()`'s process-local integer. It resets across process restarts and cannot identify a resumed turn, so it is not a durable key. Hashing generated response content was also rejected because regeneration can produce different output for the same accepted input.

### D2. Use character markers plus the encounter receipt to recover file-by-file writes

For each changed character, include `last_combat_applied_id` in the same atomic write as the character effects. After all character writes succeed, atomically write the final encounter projection with the receipt in `turn_receipts`. A matching character marker skips only that character's effects during partial recovery; a matching encounter receipt skips the completed turn. Retain receipts for the encounter's lifetime.

The character marker is intentionally only the latest applied ID: turns are serialized, so no later turn can replace it while a commit is incomplete. Completed older turns are detected by the encounter receipt list. Individual writes remain atomic; the design does not claim a cross-file transaction.

Alternative considered: write the encounter receipt before characters. That would violate the approved character-first order and could claim effects that were never persisted. A process-local ID alone would not survive restart.

### D3. Persist the final phase/round snapshot in the encounter-last commit

Derive the final `combat_round` and phase markers in Python while staging the turn projection, then include those values in the encounter-last write. Only after that durable write does post-commit work synchronize the multi-PC manager, turn queue, and session from the committed snapshot. This work is idempotent and performs no additional gameplay-state write. After a restart at this boundary, bootstrap reads the same committed snapshot and completes synchronization without advancing the round again.

Alternative considered: persist phase changes as a second post-commit encounter write. That makes the phase boundary another gameplay commit and weakens the single encounter-last projection. Persisting the final projection once keeps encounter-last precise while honoring post-commit runtime phase work.

### D4. Treat receipt durability as the success-publication gate

Do not expose the assistant narration as completed-turn output until the receipt-bearing encounter write and post-commit synchronization both succeed. Correlate success internally with `applied_id` while preserving the existing external event payload. If delivery is interrupted, replay may repeat the notification for that same turn; it MUST NOT repeat state effects. The `turn_start` event remains at loop entry and is not moved or reclassified as success.

Alternative considered: keep the legacy pre-apply narration publication. That can report a completed turn even when a later character or encounter write fails, contrary to the G7 contract.

### D5. Keep state changes additive and fault injection isolated

Readers treat missing `turn_receipts` and character applied-ID markers as empty legacy state; new optional fields are accepted by canonical validators. Runtime state writes use the repository atomic JSON helpers. Fault injection uses `COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED = False` by default and is rejected outside the isolated `tmp/combat_capture/` tree.

The metadata is internal and MUST not change model-visible prompt bytes. Preserve all nine legacy prompt SHA-256 values and the existing G1/G3/G4/G5R provider-free goldens. Do not modify current gate baselines or targets.

### D6. Reserve an optional position-delta slot for future spatial combat

The per-turn receipt and committed final encounter snapshot reserve an optional, additive `position_deltas` slot. It is absent or empty today; readers MUST treat a missing slot as empty, following the legacy rule for `turn_receipts`. When V2 spatial combat lands, Python will own positions and geometry (see `plans/version-2/mapping/combat-mapping.md`); movement will be another receipt/ledger effect type subject to the same applied-ID idempotency. Nothing in this change populates the slot, validates it beyond being optional, or reads it.

Alternative considered: add nothing and migrate later. Rejected because the receipt shape is being defined now, and an additive reserved slot is cheaper than a later receipt-schema migration.

### D7. Persist a commit manifest in the existing pre-commit history write and complete pending commits at bootstrap

Before the first character write, persist a bounded, private, versioned commit manifest (`schema_version: 1`) on the turn's history record. It contains `turn_id`, `applied_id`, `encounter_id`, `path` (`normal` or `enemy_batch`), the ordered changed-character effect payloads exactly as `commit_combat_turn` will apply them in canonical identity order, the final encounter projection or its staged operations (including the committed `combat_round`, phase markers, and receipt fields), staged reward effects, and the success narration text/payload to publish. These are the validated staged values used for the commit, not raw provider output; bounds match the normalized per-turn structures admitted by the commit coordinator, and invalid or oversized manifests fail closed rather than being truncated.

The manifest is attached to the history write that already precedes character writes. For enemy batches this is the existing `persist_history` write. For the normal path, move the existing assistant-response history save to immediately after staging and before the first character write; this changes ordering, not write count. The manifest's receipt data carries the exact staged receipt identity and round fields; `commit_timestamp` is resolved at the encounter-write boundary according to the existing durable-write timestamp rule. This adds no gameplay write: the G5T per-batch raw write budget remains history + encounter + one write per changed character. Strip all manifest metadata from every provider-bound projection through the existing allowlist projection so prompt bytes remain identical.

On combat bootstrap / `start_game`, inspect history for the newest manifest whose `applied_id` is absent from `turn_receipts`, then validate the complete manifest before writing anything. Complete the commit from that manifest only: make no provider call and do not re-plan or regenerate; skip characters whose `last_combat_applied_id` already matches, write only missing character effects in canonical identity order, then make the single encounter write with the stored final projection, receipt, committed phase, and round. Synchronize post-commit runtime state from that committed snapshot and perform one success-publication operation using the stored narration text/payload, internally correlated with the same `applied_id`, before normal resume flow. A manifest with a matching receipt is a no-op: do not reapply effects, and require no republication beyond the existing resume flow. A corrupt or invalid pending manifest fails bootstrap with an explicit error before any recovery write; recovery never guesses or regenerates missing payloads.

Alternatives considered: regenerating the response can produce different effects or narration and cannot reconstruct the exact enemy-batch ledger after partial writes; a separate manifest file adds a gameplay write beyond the G5T budget and creates a cross-file ordering hazard; asking the user to resend creates a new `turn_id` and cannot resume the accepted turn.

### D8. Match G7 enemy-batch expectations to legal initiative and persisted effects

G7 keeps the existing Capture_Arena PC initiative inputs unchanged (P1 Acheron 18; P4 Acheron 20, Merisiel 18, Kira 16, Vitreol 14) and goblin initiatives at 10/8. The production turn queue rolls d20 plus each PC's persisted initiative input, so P4 target identity can vary by reachable order. Do not inject synthetic initiative values or pin the P4 enemy-batch expectation to one PC. The named enemy-batch encounter IDs are selected by running the production manager and deterministic planner over every distinct reachable runtime order; each selected batch must be accepted, hit, and yield exactly one changed PC for every order. The current P4 fixture has 24 reachable orders and uses `turn_commit_p4_130`; P1 uses `turn_commit_p1_002`.

The manifest written by an interrupt is authoritative for the enemy-batch target. Recovery reads the retained pre-restart manifest, requires its single effect to name one party PC, and verifies that the same PC is the only changed character through recovery while retaining receipt, applied-ID marker, and duplicate-effect checks. `after_character_write:2` remains applicable to P4 normal turns only; the enemy-batch path's single-PC effect has no second character-write boundary.

### G7 preroll determinism seam

G7 enemy-batch launches export the fixture's valid `NEQ_COMBAT_PREROLL_SEED`. Combat startup creates one local `random.Random` only when the existing fault-injection flag is enabled, the installed runtime root passes the repository-local `tmp/combat_capture` guard, and the seed is valid; that same generator is injected into initial and subsequent preroll dependencies. Ordinary combat retains the module-level random callables, and no process-wide random state or enemy-resolution seed derivation changes. Seeding the process-wide generator was rejected because it would perturb unrelated runtime decisions.

## Risks / Trade-offs

- **A process can stop between separate character-file writes** -> Persist the same `applied_id` marker with each character update and resume only the missing writes before the encounter commit.
- **Encounter receipt history grows with combat length** -> Retain it only for the owning encounter's lifecycle; do not silently discard receipts for a resumable encounter.
- **A notification can be repeated if transport delivery and acknowledgement straddle a restart** -> Associate retries with the durable `applied_id` internally, preserve the existing payload, and make no exactly-once transport claim; mechanical effects remain deduplicated by durable state.
- **Turn metadata could alter prompt inputs** -> Strip identity metadata during prompt assembly and require the nine fixed prompt-hash guards.

## Migration Plan

1. Add backward-compatible readers for missing receipt arrays and character markers; keep existing replay guards active.
2. Persist `turn_id`, stage complete turn projections, attach the bounded commit manifest to the existing pre-commit history write, add character markers, and route writes through the single character-first/encounter-last coordinator.
3. At combat bootstrap, complete pending manifests from stored effects without provider calls or re-planning; then move manager/queue synchronization and success publication behind the durable encounter write and implement provider-free interruption tests with fault injection default-off.
4. Run focused 1-PC and 4-PC suites, existing replay tests, G1/G3/G4/G5R golden checks, compat33 prompt parity, and all nine static prompt hashes.
5. After software checks pass, including real `start_game` recovery for each pre-receipt boundary with unchanged prompt hashes and G5T write counts, the primary orchestrator runs and reviews G7 in the isolated Capture_Arena sandbox; preserve evidence under the required run directories.

### Rollback

Disable fault injection unconditionally. If the new writer must be rolled back, first reconcile or complete every pending turn using its persisted identity and receipt/character markers. Retain additive receipt and marker fields and the existing replay guards; do not restore the legacy writer while a partial commit remains unresolved.

## Open Questions

None blocking. The phase boundary is resolved by committing the final encounter phase/round snapshot before runtime synchronization; the history manifest closes same-turn recovery across process restarts; `turn_id` is persisted before effects and determines `applied_id`; and `turn_start` remains pre-input telemetry rather than success publication.
