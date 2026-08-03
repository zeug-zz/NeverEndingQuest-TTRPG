## Context

The current final-editor change correctly preserves a full-module validation gate. Well of Ruin fails before the editorial boundary with 86 validation failures: reference integrity, spatial contract, and party-calendar validation. The existing accurate-ingest path calls `ModuleBuilder.build_module()` directly and does not reliably run the older `ModuleGenerator.save_module()` monster reference closure. It also allows final LLM-generated locations/connectivity to drift from spatial solver expectations and still contains prompt/readiness paths that can leave invalid calendar month values such as `Hammer` until too late.

The final editor is designed for editorial reconciliation of bogus source atoms, not structural repair. Structural ModuleBuilder output must be made validator-clean before final reconciliation is invoked.

## Goals / Non-Goals

**Goals:**

Contract Layer (MUST):

- Accurate-ingest ModuleBuilder output SHALL run deterministic structural repair before final-editor routing.
- Monster references SHALL be closed, explicitly unresolved, or fail the build before final-editor invocation.
- Spatial/cardinal/map artifacts SHALL be made self-consistent after final location generation.
- Party tracker calendar values SHALL be normalized or rejected before full validation.
- Fatal validation categories SHALL override any existing accepted final reconciliation report.

Guidance Layer (SHOULD):

- Reuse existing closure/repair utilities and reports where possible.
- Preserve source names and source topology intent while repairing structural representation.
- Keep tests provider-free and fixture-driven.

**Non-Goals:**

- Do not broaden the LLM final editor into a schema/spatial/monster repair agent.
- Do not lower validation severity for reference integrity, spatial contract, or party schema failures.
- Do not change benchmark thresholds or source-fidelity scoring to mask structural failures.
- Do not rewrite original source graph, normalized packet, blueprint, backstage audit, or uploaded source artifacts.

## Decisions

### Decision 1: Run repair after ModuleBuilder output, before final blocker classification

Contract Layer (MUST): structural repair SHALL run after ModuleBuilder has written canonical module artifacts and before final blocker classification determines whether final-editor reconciliation is allowed.

Rationale: the validation failures are defects in generated module structure. Running repair after generation lets Python inspect actual artifacts rather than guessing from prompts.

Alternatives considered: adding more prompt instructions to ModuleBuilder. Rejected as insufficient because spatial and monster closure must be Python-authoritative and deterministic.

### Decision 2: Extract or reuse monster closure as a shared accurate-ingest utility

Contract Layer (MUST): the accurate-ingest ModuleBuilder path SHALL achieve parity with the existing module-generator monster closure contract: every structured monster reference is backed by a module-local schema-valid monster artifact or an explicit unresolved diagnostic that blocks the build when required.

Guidance Layer (SHOULD): reuse `_ensure_monster_reference_closure(...)` behavior from `core/generators/module_generator.py` by extracting a small shared helper if direct reuse would couple too tightly to `ModuleGenerator` internals.

### Decision 3: Treat spatial repair as representation repair, not creative redesign

Contract Layer (MUST): spatial repair SHALL preserve generated/source location identities and recompute only representation needed for spatial validation: coordinates, cardinal adjacency, map links, and area connectivity consistency.

Guidance Layer (SHOULD): use existing spatial solver/normalization utilities and write a compact repair report showing before/after counts, unresolved topology diagnostics, and any locations that could not be placed.

### Decision 4: Normalize calendar before validation and remove known-bad prompt seed

Contract Layer (MUST): party tracker calendar data SHALL use schema-valid month values before final validation or fail with an explicit calendar diagnostic.

Guidance Layer (SHOULD): reuse `_deterministic_fix_party_month` semantics from the readiness gate and remove or replace the `Hammer` example in generator prompts so future builds are less likely to emit invalid months.

### Decision 5: Fatal structural blockers override accepted reconciliation reports

Contract Layer (MUST): if full-module validation reports schema, reference-integrity, spatial-contract, party, JSON, or topology structural failures, final-editor invocation SHALL be skipped and any existing accepted reconciliation report SHALL NOT make the build playable.

Guidance Layer (SHOULD): preserve the existing accepted report on disk for auditability but ignore it for routing until structural validation passes.

## Risks / Trade-offs

- Risk: shared monster closure extraction touches older generator code -> Mitigation: keep the extracted API narrow and add parity tests proving existing closure behavior is unchanged.
- Risk: spatial repair changes authored traversal semantics -> Mitigation: only repair validator-required representation and fail closed when topology cannot be reconciled safely.
- Risk: calendar normalization silently maps an intentional nonstandard calendar -> Mitigation: restrict automatic normalization to known invalid Forgotten Realms style month names or existing readiness helper semantics and report every change.
- Risk: build remains blocked more often -> Mitigation: expose fatal diagnostics clearly and do not route structural failures to editorial reconciliation where they would produce misleading source-fidelity reports.

## Migration Plan

1. Add provider-free tests that reproduce Well-of-Ruin-style structural failures at the routing/helper level.
2. Implement shared monster closure or adapter and wire it into accurate-ingest ModuleBuilder output.
3. Implement spatial repair/reporting and wire it after final location/connectivity generation.
4. Implement early party calendar normalization and remove the known-invalid prompt example.
5. Harden final-editor routing to skip on fatal structural validation even when accepted reconciliation exists.
6. Run targeted tests, Well of Ruin validation, publishability audit, and OpenSpec validation.

Rollback strategy:

- Disable the new structural repair invocation and return to the current blocked behavior. Do not allow final-editor acceptance to bypass structural validation.

## Open Questions

- Whether the monster closure helper should live under `utils/` or remain under `core/generators/` as a shared generator utility.
- Whether spatial repair should be a standalone utility or an extension of the existing spatial solver normalization layer.
