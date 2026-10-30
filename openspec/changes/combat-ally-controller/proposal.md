# Proposal

## Why

Allied NPCs currently share the DM-controlled combat group, so they lack a bounded, intelligent controller distinct from hostile enemy resolution. Add a default-off ally controller that can respond to player directives and choose Python-issued tactical options while preserving initiative order, Python-owned mechanics, and the Narrator's voice.

## What Changes

- Add a separate, perception-limited ally batch using a structured plan and a narration request; Python builds legal options, validates selected IDs, resolves mechanics, and uses a deterministic rule fallback for missing or illegal choices.
- Limit the current applied ally menu to options with existing Python legality/effect contracts, including legal attacks and authored `take_cover` only where its current contract allows it. Document movement/protection intents as non-operative placeholders for the later grid-mapping work; do not issue or apply them now.
- Place the ally batch between the initiative-winning side and the other side: hostile enemies, allies, PCs when the DM group wins; PCs, allies, hostile enemies when the PC group wins. Keep existing hostile batch behavior and existing G5T/G5R evidence and goldens unchanged.
- Add Python-parsed `/cmd <AllyName> <free text>` directives. Validate active allied NPC identity, normalize and bound text, acknowledge in the UI, coalesce repeated directives per ally before the one allowed re-plan, and never treat `/cmd` as a PC action or phase transition. A directive guides but does not force the ally's action.
- Prefetch ally tactical intents during an eligible PC phase with one initial request and at most one state-edge/directive-triggered re-plan. Keep background request accounting separate and bounded; synchronous ally planning and narration remain at most two provider calls per accepted ally batch.
- Default current allies to loyal. Offer no model-controlled flee or surrender choices; keep side surrender, disloyal-NPC flight, and extraction of surviving allies DM-owned.
- Keep Python-generated combat chat replies concise and in the existing Narrator/Dungeon Master voice. A pending `/cmd` may receive an in-character ally response as part of the ally batch narration, without a separate reply call.
- Add default-off controller/prefetch flags, a G5A Capture_Arena scenario and provider-free coverage, and preserve the nine legacy prompt hashes plus byte-identical G1/G3/G4/G5R and existing G5T offline re-evaluation.

## Capabilities

### New Capabilities

- `combat-ally-controller`: Separate legal-menu ally planning, `/cmd` directives, loyalty, prefetch, call budgets, and receipt-backed application.
- `combat-python-combat-voice`: Consistent Narrator/Dungeon Master voice for Python-authored combat chat responses without changing their mechanics.

### Modified Capabilities

- `combat-latency-smoke-fixtures`: Add G5A P1/P4 scenarios, isolated evidence, and primary-owned live acceptance checks.

## Impact

Expected implementation touchpoints include combat command parsing and response formatting, turn/initiative orchestration, a separate ally planner and perception projection, PC-phase prefetch, model configuration, combat turn commit staging, provider-free tests, and Capture_Arena/report tooling. Ally effects from one accepted `/end` input must use the existing character-first/encounter-last receipt and manifest path. No external API or party-size-specific state model is introduced; the 1-PC party and 4-PC party remain required shapes.
