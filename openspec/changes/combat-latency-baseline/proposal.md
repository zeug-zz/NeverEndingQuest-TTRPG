# Combat Latency Baseline

## Why

Combat responsiveness is a product requirement for TABLETOP MODE, where one
facilitator enters actions for several player characters. The current combat
path has no trustworthy, per-turn baseline that attributes wall-clock time,
provider work, compression work, file operations, and deterministic decision
paths. Without that evidence, later router, decomposition, and latency changes
cannot be compared without confounding structural and provider changes.

## Objective

Create an opt-in, read-only combat turn trace and a provider-free report path
that captures the pre-router, pre-model-swap OpenAI baseline. The change MUST
provide fixed 1-PC party and multi-PC smoke fixtures, decision-event fields,
and enough bounded telemetry to ratify or adjust the provisional latency
targets before later combat phases.

The Contract Layer MUST be normative and testable. The Guidance Layer SHOULD
describe preferred implementation choices without overriding the contract.

## Scope

### MUST

- Add opt-in trace instrumentation with the gate defaulting to OFF.
- Capture provider sites, compression/cache activity, file operations, stage
  timings, NL fast-path outcomes, and decision events.
- Keep instrumentation fail-open and read-only.
- Add fixed MP and 1-PC party smoke fixtures and a provider-free report script.
- Add a reusable scripted capture ensemble (lean sandbox copy seeder,
  `Capture_Arena` capture module, and an agent-driven `playwright-cli`
  skill/checklist) that executes the live baseline in isolation and preserves
  its traces under `tmp/`.
- Preserve existing provider-call counts, prompts, mechanics, and game-state
  behavior.

### SHOULD

- Keep the trace format append-only JSONL with bounded event payloads.
- Keep instrumentation helpers outside the combat state authority so later
  decomposition can move combat stages without changing the trace contract.
- Make report output stable enough for target-ratification review and diffing.

## Explicit Non-Goals

- No runtime combat behavior, mechanics, routing, retry, timeout, or state
  mutation changes.
- No provider calls added or removed, including no Jev implementation or live
  Jev dependency.
- No product behavior change from the capture ensemble; it is test tooling only
  (isolated `tmp/` copy, no installed-tree writes, no runtime contract changes).
- No prompt edits; prompt files MUST remain byte-identical.
- No model swap, OpenRouter activation, router migration, or provider policy
  change.
- No compression redesign or validation-routing redesign; this change records
  their existing behavior only.
- No replacement of the existing combat suites or game-state persistence.
- No production reports or baseline data committed under `reports/`.

## Rollout Risk And Fallback

The principal risk is observer overhead, malformed trace output, or an
instrumentation exception affecting combat. The trace writer MUST isolate all
failures, avoid blocking combat, and degrade to no trace rather than raising.
The disabled path MUST perform zero trace file writes and add no measurable
overhead.

Rollout SHOULD begin with the flag OFF, then use the fixed fixtures to capture
the baseline in a controlled run. If the trace changes timing, produces
corrupt output, or causes any gameplay symptom, the operator MUST turn the
config gate OFF and continue using the unchanged combat path. The fallback is
therefore a configuration rollback, not a data or save migration.

## 1-PC Party And Multi-PC Compatibility Impact

1-PC party behavior MUST remain unchanged and MUST be covered by the one
round fixture. Multi-PC behavior is the primary measurement path and MUST be
covered by the fixed 4-PC, 3-round, one-enemy-batch fixture. Trace records MAY
identify the mode, but trace collection MUST NOT alter phase gates, initiative,
roster integrity, death-save handling, enemy batches, surrender/exit behavior,
or resume behavior.

## Provider-Outage Behavior

This change adds no provider calls and does not change provider fallback or
outage handling. Existing provider calls, errors, retries, and fallback
behavior MUST be observed without interception that changes their outcome. If
trace instrumentation fails during a provider outage, the trace failure MUST
be swallowed and the existing combat outage behavior MUST remain authoritative.

## Acceptance Boundary

Gate G1 is met only when a baseline is captured on the OpenAI stack, report
output is recorded for target review, the disabled path has zero trace writes,
and 1-PC party/multi-PC party smoke plus the existing combat verification
commands pass. Target ratification or adjustment remains an owner decision
after measurement.
