# Proposal

## Why

The frozen M1 packet averaged 2.625/5 for legibility and 2.875/5 for usefulness, below its frozen 3.5 thresholds. Owner review identifies actionable mise-en-scene, including a staged arrival, as the goal. This prospective follow-up specifies an offline fixture-authoring/projection prototype and a leakage-controlled evaluation proposal; it does not convert pilot evidence or redesign examples into results.

## What Changes

- Specify a compact, provider-free prototype that validates and projects supplied fixtures; this does not test whether an LLM Builder can author a scene.
- Add a Builder-authored staged arrival prose layer to the matched evaluation conditions, bound to the same structured facts, IDs, and provenance.
- Keep a four-condition comparison and proposed protocol: 6 held-out scenes x 4 conditions produce 24 artifacts and 48 P1/P4 episodes (24 each); proposed gameplay ceilings are 1,152 initial and 2,304 absolute provider attempts, with a distinct advisory maximum of 30 attempts (24 holdout + 6 calibration, one per item) and a 6-hour live ceiling including setup, teardown, and retries. All counts, budgets, thresholds, and limits remain unapproved/unfrozen; recommend offline work before any live evaluation.
- Record that PR114 is approved in principle with required revisions. After revisions, green CI, and an inbox report, stop for Overseer re-review; only later approval permits merge or offline implementation.

## Central objective: Narrator-first

The prototype optimizes the NEQ LLM's spatial comprehension and actionable, coherent narration first. Cumulative knowledge-filtered player maps are secondary projections of the same authored facts plus committed discoveries—not a full atlas or production S5.

## Scope

- Define testable offline requirements for provenance, unknowns, scene scope/orientation, approaches and thresholds, focal relationships, multi-cell extents, usable space, stable fixed/mobile anchors, and staged arrival prose. Extraction preserves unknown orientation; an explicitly Builder-authored orientation is allowed only when checked against approved topology/compass frames.
- Compare matched facts as A structured relationships, B prose-only control, C structured relationships plus schematic grid, and D structured relationships plus grid plus Builder-authored staged arrival prose. D adds presentation, not facts; this is not a production-format selection.
- Specify provider-free structural and positional-coverage diagnostics and a proposed development/calibration and held-out protocol. All proposed counts, thresholds, attempt limits, and time ceilings remain unapproved and unfrozen.
- Treat future evaluation of LLM-authored staging as separately authorized work with its own unapproved protocol, budget, and source provenance. It is not covered by the 30-attempt advisory proposal or gameplay budget and is not a current task or provider call.
- Keep production S/SC integration, runtime prompt/schema/state changes, existing-module backfill, Network client work, TITAN seed generation, and Firelight family migration in their separately reviewed owner changes. No final format, combat, or data-pipeline choice is made here.
- Revise only this change's planning artifacts. Do not accept ADR-0034, alter main specs or frozen pilot records/ratings, call a provider, start a live gate, or implement runtime Narrator behavior. The prototype does not implement the runtime Narrator.

## Non-goals

- Production core/web/modules/schema/prompts, runtime state/persistence, module writes or backfill, ADR-0034 acceptance, SP3b reopening, changes to frozen artifacts/ratings, TITAN seed generation, live/provider evaluation, or any final format/combat/data choice. Section 2 evaluation tasks remain NOT AUTHORIZED.

## Capabilities

### New Capabilities

- `tt-mise-en-scene-authoring-projection`: A prospective contract for offline scene-staging/relationship prototypes, matched projections, provider-free diagnostics, and separately authorized evaluation; it does not specify production runtime integration.

### Modified Capabilities

None. Existing spatial, scene-authority, Builder, and narrator specs continue to own their current bounded contracts; this capability defines their proposed cross-track seam without silently replacing them.

## Impact

Future prototype code and tests, if later approved, would use proposed paths under `scripts/mise_en_scene/` and `scripts/test_mise_en_scene_*.py`; these paths and tests are not claimed to exist. No production schema, module, runtime, prompt, persistence, or provider path is in scope. Network retains authorization, transport, and client ownership. Under accepted ADR-0033, Firelight decides legality only for migrated families through the Python bridge; unmigrated families retain Python guards. ADR-0034 remains Proposed; a runtime owner change needs an accepted or revised authority decision, but an offline prototype does not depend on accepting that draft.
