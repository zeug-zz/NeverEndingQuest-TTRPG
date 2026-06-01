## Overview

This change turns accurate-ingest from "source-fidelity can pass" into "web GUI Module Builder output is playable and publishable." The first acceptance target is The Hidden City of Numillian because it now passes source fidelity but still fails validation/publishability due schema and topology problems.

## Contract Layer (MUST)

- The GUI accurate-ingest pipeline MUST NOT mark a module playable when validation or publishability fails.
- The pipeline MUST reconcile plot point `location` references against emitted area/location IDs before final validation.
- The pipeline MUST emit schema-valid `party_tracker_BU.json` defaults.
- The pipeline MUST refresh and compare source-fidelity, toolkit build, validation, and publishability reports in dependency order.
- The pipeline MUST preserve source-fidelity pass status while fixing schema/topology readiness issues.
- The pipeline MUST keep runtime files ignored and canonical publication artifacts trackable without `git add -f`.
- The pipeline MUST provide operator-facing next-action routing when a module is not playable.

## Guidance Layer (SHOULD)

- Prefer small deterministic post-build normalization helpers over broad generator rewrites.
- Prefer one shared report-composer function so GUI and CLI readiness agree.
- Use Numillian fixtures to lock the initial contract, then test at least one additional synthetic module fixture for generality.
- Preserve source-fidelity repair utilities as independent evidence/repair layers; this change should compose them rather than duplicate them.

## Architecture

### 1. Plot/Location ID Reconciliation

Add a deterministic post-build step that maps source/map-key plot locations to emitted location IDs. For Numillian, PP001-PP013 currently use `THE01`-`THE13` while the emitted graph uses `A01`-`A18`. The reconciler should use stable source labels, source room numbers, semantic authority, or location names to map plot refs to emitted IDs.

Fail closed when a plot point location cannot be mapped. Do not silently drop plot points.

### 2. Party Tracker Schema Normalization

Normalize generated `party_tracker_BU.json` world defaults against schema enums. For Numillian, month `Hammer` is invalid under the current schema. The post-build normalizer should either map external calendar names to supported values or emit schema-native defaults.

### 3. Artifact Cleanliness

After clean rebuild/finalization, canonical artifact families must be internally coherent:

- `module_context.json` and `module_context_BU.json` parity for source locks and canonical NPC context.
- `module_plot.json` and `module_plot_BU.json` parity for required plot/schema fields.
- `areas/*_BU.json` and `map_*_BU.json` must match the current module graph.
- stale deleted area/map files from prior rebuild strategies must not remain as accidental git diffs.

### 4. Report Agreement

Report generation must happen in a deterministic order:

1. validation/schema checks
2. source-fidelity benchmark/report
3. toolkit build report
4. publishability audit
5. GUI status payload

The final GUI status must show playable only if every required report agrees.

### 5. GUI Status Routing

The web GUI must distinguish:

- source-fidelity blocked
- schema validation blocked
- topology/plot graph blocked
- media/monster blocked
- publishability blocked
- playable/published ready

## Risks

- Overfitting to Numillian ID patterns. Mitigation: implement name/source-label mapping and add temp fixture tests.
- Accidentally weakening publication gates. Mitigation: tests assert gates fail closed when reports disagree.
- Runtime artifact pollution. Mitigation: verify gitignore contract and canonical artifact set before completion.

## Rollback

If the new playable gate blocks too aggressively, the existing build output can remain available as a non-playable diagnostic artifact while the GUI withholds published/playable status.
