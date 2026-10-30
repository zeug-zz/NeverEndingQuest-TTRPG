# Proposal

## Why

The G5R-accepted deterministic enemy resolver makes enemy mechanics reproducible, but its fixed target selection and interim near-death fallback cannot express coordinated, perception-limited squad choices. Add a bounded commander planning layer above the Python-owned resolver so tactics can improve without granting the model authority over mechanics or exceeding the two-request G5T budget.

## What Changes

- Add optional encounter tactic tiers: `rule` (the legacy/default deterministic policy) and `commander` (one structured plan for the current enemy side). Plans select only Python-issued menu option IDs; missing, invalid, or rejected per-actor choices use the rule tier with a bounded reason.
- Limit commander inputs to explicit perception facts and legal current options. Permit only menu-defined attacks, authored cover choices, per-creature flee/surrender, commander withdrawal orders, and side-level surrender; flee uses Disengage without grid movement.
- Persist flight and surrender through the existing `defeated` status plus optional encounter-creature `defeatReason` (`fled` or `surrendered`); narration receives that reason. Reuse existing exit/XP handling without changing XP policy.
- Add structured location tactical features and encounter-scoped cover state. Apply cover through a shared effective-AC lookup for enemy resolution and PC `/att`, with cover bonuses derived from the authored cover type.
- Add a separately default-off prefetch flag. At PC-phase start, prefetch may request bounded conditional standing orders for the identified upcoming batch; Python compiles completed orders against the current legal menus at `/end`, without a planner call there. One initial request plus at most one event-triggered re-plan is allowed per batch; if the standing-order path was selected but no valid set completed, actors use rule-tier defaults rather than a synchronous re-plan. Disabled or ineligible prefetch leaves the existing synchronous plan path unchanged.
- Add the default-off `COMBAT_TACTICAL_BRAIN_ENABLED` and `COMBAT_TACTICAL_PREFETCH_ENABLED` flags. The brain also requires the existing deterministic enemy resolver flag. Existing 1-PC-party and multi-PC-party behavior remains unchanged while these flags are off.
- Define G5T with new named commander captures, behavioral evidence, and unchanged absolute targets: at most two provider requests per accepted commander batch, median batch work-only latency <= 15.0 seconds, at most one history write plus one encounter write plus one character write per distinct character whose canonical state changed in the batch, and 100% legal plan choices. Prefetch has an optional, separately reported sub-gate.
- Extend bounded traces, report output, and capture tooling while preserving G1/G3/G4/G5/G5R defaults, identities, and evaluator behavior. Keep the shipped feature flags OFF until the orchestrator records a G5T PASS and a separate rollout decision is approved.

## Capabilities

### New Capabilities

- `combat-tactical-brain`: Defines rule/commander tiers, menu-constrained plans, perception boundaries, validation, and per-creature/side self-preservation semantics.
- `combat-tactical-cover`: Defines authored tactical features, encounter cover state, and effective-AC calculation across enemy and PC attack paths.
- `combat-tactical-prefetch`: Defines opt-in PC-phase standing orders, current-menu compilation, bounded re-planning, lifecycle, and separate request accounting.
- `combat-tactical-g5t`: Defines G5T commander scenarios, acceptance targets, behavioral evidence, and the optional prefetch sub-gate.

### Modified Capabilities

- `combat-decision-trace-events`: Add bounded tactical-plan outcomes, fallback reasons, and cover outcomes.
- `combat-turn-trace-schema`: Add bounded plan correlation, prefetch status, and cover observations without exposing prompt or game-state payloads.
- `combat-latency-report-script`: Report G5T calls, latency, writes, plan legality, and optional prefetch results while preserving earlier gate output.
- `combat-latency-smoke-fixtures`: Add separate named commander scenarios without changing existing G1/G3/G4/G5/G5R scripts or identities.

## Impact

Runtime touchpoints include `core/combat/` enemy planning, enemy-batch orchestration, effective-AC resolution, and the PC `/att` command path; encounter and location schemas; `model_config.py`; and provider-free tests. Capture/report touchpoints are the existing Capture_Arena seeder, driver, evidence validator, trace, and latency report. Python remains authoritative for legality, attack rolls, damage, status, cover, defeat reason, and persistence. Commander planning uses the existing router, so timeout, retry, outage, quota, and terminal-error behavior remain router-owned. The feature is opt-in and must preserve the 1-PC-party regression floor and multi-PC-party behavior.
