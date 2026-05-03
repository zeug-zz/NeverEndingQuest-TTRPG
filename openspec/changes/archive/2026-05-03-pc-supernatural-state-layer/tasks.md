# Tasks

## 1. Schema and state helpers

- [x] 1.1 Add additive `creatureTypes` and `supernaturalStates` fields to `schemas/char_schema.json`.
- [x] 1.2 Add focused validation/normalization helpers for supernatural state records without changing life-state normalization semantics.
- [x] 1.3 Add regression coverage proving `status` remains limited to life-state values and playable undead/corrupted PCs use the new fields.

## 2. Resurrection/corruption persistence

- [x] 2.1 Update `resurrectCharacter` corrupted/altered modes to write schema-valid `supernaturalStates` records.
- [x] 2.2 Convert or supersede existing `_supernatural_metadata` writes so future runtime surfaces read the new fields.
- [x] 2.3 Preserve dead-state stickiness for generic HP/status updates.
- [x] 2.4 Add focused positive and negative tests for ordinary resurrection, corrupted resurrection, playable undead resurrection, and invalid payloads.

## 3. Runtime and prompt projection

- [x] 3.1 Project supernatural state summaries into multi-PC DM Note full and condensed PC formatting.
- [x] 3.2 Project bounded state summaries into conversation context and character sheet compression where relevant.
- [x] 3.3 Project creature type and state summaries into combat prompt/truth context for touched combatants.
- [x] 3.4 Add source-contract tests proving projection preserves `status` as mechanical life-state authority.

## 4. Player-facing display

- [x] 4.1 Display supernatural state labels and creature type badges on the Character Sheet without replacing HP/status display.
- [x] 4.2 Include bounded supernatural state summaries in Character Sheet PDF output.
- [x] 4.3 Add UI/source tests for badge rendering and PDF field inclusion.

## 5. Migration and Vitreol review gate

- [x] 5.1 Add deterministic migration or repair support for existing `_supernatural_metadata` if present.
- [x] 5.2 Prepare a targeted Vitreol data patch but do not apply canon-sensitive classification until review confirms `humanoid + corrupted` versus `humanoid + undead + corrupted`.
- [x] 5.3 If review approves a Vitreol patch, apply it atomically and validate the character file.

## 6. Verification

- [x] 6.1 Run `.venv/bin/python -m py_compile` on all modified Python files.
- [x] 6.2 Run focused supernatural state schema/action/projection tests.
- [x] 6.3 Run existing dead-state and resurrection regression tests.
- [x] 6.4 Run Character Sheet/PDF focused tests if UI/PDF surfaces change.
- [x] 6.5 Run `openspec validate pc-supernatural-state-layer`.
