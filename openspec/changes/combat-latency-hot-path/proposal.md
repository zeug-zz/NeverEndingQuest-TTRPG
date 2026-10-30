# Proposal

## Why

The combat runtime still spends avoidable work on per-message compression, full validation, repeated state synchronization, and unconditional diagnostic dumps. Build 4 can reduce that hot-path overhead now that the router owns provider transport and the combat stages have explicit boundaries, while proving structural improvement against a same-model current reference rather than the historical G1 capture.

## What Changes

- Define bounded runtime latency work for combat: verify router-owned timeout coverage; compress at round boundaries and deterministically trim stale history; gate debug dumps; conservatively route validation skips; memoize byte-identical prompt context; synchronize encounters once per turn and persist only changes; express retry profile only through the router's `retry_tier`; and canary the existing NL PC-phase fast path with telemetry and LLM fallback.
- Before the G5 before-reference, add bounded authoritative phase context to dynamic validator messages, trace the existing `/att` hit fast-path decision, and set explicit single-attack metadata in the Capture_Arena 1-PC and 4-PC Goblin fixtures. The general preroll attack-count inference defect remains out of scope.
- Extend the existing capture, trace, fixture, and report pipeline with a G5 gate and isolated evidence bundles that attribute provider calls and writes per action/batch, separate work-only timing from quiet-window timing, and report skip/NL outcomes.
- Require primary-owned equivalent before/after captures for the fixed 4-PC/3-round/enemy-batch and 1-PC/1-round fixtures, using the same current provider/model, seed, and measurement method. Keep G1's gpt-5.6-luna evidence historical and distinct.
- The runtime changes MUST preserve mechanical authority, static combat prompt assets, roster/phase/death-save/initiative/enemy-batch and resume-replay behavior, existing G1 output, and G3/G4 evaluation behavior. The approved bounded dynamic validator context is separate from candidate claims; G5 targets MUST remain fixed unless the owner approves a change.
- Non-goals: router activation, OpenRouter/provider/model changes, Jev, resolver expansion, media, Titan, party-mode flag removal, Build 5 remaining callsite migration, and Build 6 commit-before-publication work.

## Guidance Layer (SHOULD)

The implementation SHOULD extend the existing trace, capture, fixture, and report surfaces rather than add a parallel framework.

## Capabilities

### New Capabilities

- `combat-turn-latency-control`: Defines the constrained runtime hot-path work, compatibility invariants, and fixed G5 acceptance boundary as one cohesive combat-turn behavior.

### Modified Capabilities

- `combat-turn-trace-schema`: Add bounded per-action/batch work attribution, run identity, and separate work-only and quiet-window timing fields.
- `combat-decision-trace-events`: Record validation-skip and NL fast-path outcomes, including fallback and unavailable outcomes, while reserving the `jev_*` reason namespace.
- `combat-latency-report-script`: Report G5 attribution, skip/NL rates, comparable before/after results, and explicit target verdicts without runtime dependencies.
- `combat-latency-smoke-fixtures`: Add G5 gate selection and isolated capture-bundle contracts while preserving existing fixture behavior and G1/G3/G4 paths.

## Impact

Runtime touchpoints include `core/combat/validation.py`, `core/combat/turn.py`, `core/combat/combat_manager.py`, `core/combat/decisions.py`, the combat compression components, and the existing router retry-profile interface. Tooling touchpoints are the existing combat latency fixtures, capture driver/evidence validator, report script, and capture skill. Changes affect shared combat paths and therefore retain both 1-PC-party and multi-PC compatibility. The only schema additions are bounded internal trace/report evidence fields; no public API, provider, or game-state schema is introduced. Provider outage/quota behavior and the router's existing retry/fallback path remain authoritative; a failed NL parse falls through to the existing LLM path, and setting `COMBAT_PC_PHASE_NL_FAST_PATH` to `False` disables that canary.
