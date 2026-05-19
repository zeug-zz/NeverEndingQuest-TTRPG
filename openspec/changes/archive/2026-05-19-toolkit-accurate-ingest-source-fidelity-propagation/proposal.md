# Proposal: Accurate-Ingest Source-Fidelity Propagation

## Problem

The accurate-ingest GUI pipeline can produce source-fidelity findings while building a module, but the final publication path does not yet have one authoritative module-level source-fidelity artifact to consume.

Current risk points:

1. Workspace-level source-fidelity reports can be produced during GUI build but not persisted into the final module artifact set.
2. `scripts/audit_module_publishability.py` currently reads `accurate_ingest_benchmark_report.json`, which is benchmark-specific and can be missing, stale, or less complete than the GUI build's source-fidelity rollup.
3. `toolkit_build_report.json` can diverge from the final publishability audit because source-fidelity status is not propagated through one canonical final contract.
4. Legacy modules still need fail-open `source_fidelity_status="unknown"` behavior when no accurate-ingest artifacts exist.

This creates a false-confidence failure mode: an accurate-ingest GUI build can be degraded or blocked by source fidelity during build, while the final publishability audit reports `unknown` or consumes stale benchmark data.

## Objective

Create and consume one module-level accurate-ingest source-fidelity artifact so the same final status flows through:

1. GUI/workspace build output.
2. Module artifact set.
3. `toolkit_build_report.json`.
4. CLI publishability audit.
5. Final GUI publishability status.

## Proposed Solution

Add a canonical module-level artifact:

```text
modules/<slug>/source_fidelity_report.json
```

The report SHALL preserve the final accurate-ingest source-fidelity status and supporting category details from the GUI/workspace build. `audit_module_publishability.py` SHALL prefer this module-level artifact over benchmark-specific reports when present.

Implementation scope:

1. Define a stable `source_fidelity_report.v1` JSON contract.
2. Persist or copy the final workspace/source-fidelity rollup into the module directory after seed/enrichment/build-fidelity completes.
3. Surface the same status and categories in `toolkit_build_report.json`.
4. Update publishability audit precedence to prefer `source_fidelity_report.json`, then fall back to `accurate_ingest_benchmark_report.json`, then `unknown`.
5. Preserve legacy fail-open behavior for non-accurate-ingest modules with no source-fidelity artifact.

## Non-Goals

- This change does not regenerate Numillian or mutate module data.
- This change does not implement new source-fidelity scoring logic.
- This change does not change the deterministic benchmark runner except through read precedence if needed.
- This change does not implement GUI layout changes unless route/status payload tests prove a narrow field propagation is missing.
- This change does not implement enrichment provider orchestration.

## Contract Layer (MUST)

- Accurate-ingest builds MUST persist final source-fidelity status to `source_fidelity_report.json` in the module directory.
- `toolkit_build_report.json` MUST include the same effective `source_fidelity_status` and category details.
- `audit_module_publishability.py` MUST prefer module-level `source_fidelity_report.json` over `accurate_ingest_benchmark_report.json`.
- `source_fidelity_status="blocked"` MUST block final publishability when source-fidelity gating is enabled.
- Legacy modules without accurate-ingest source-fidelity artifacts MUST remain fail-open with `source_fidelity_status="unknown"`.
- Stale benchmark reports MUST NOT override a current module-level `source_fidelity_report.json`.

## Guidance Layer (SHOULD)

- Keep the artifact contract additive and compatible with existing benchmark categories.
- Include provenance fields so a reviewer can trace module artifact status back to workspace/source hash.
- Prefer small helpers for report loading and normalization over broad publishability rewrites.
- Reuse `utils/toolkit_publication_gate_composer.py` composition behavior where possible.
- Keep GUI template changes out of scope unless route payload tests prove they are required.

## Risks

| Risk | Mitigation |
|---|---|
| Existing modules without source-fidelity reports become blocked | Explicitly preserve fail-open `unknown` for legacy modules. |
| Benchmark and final source-fidelity reports disagree | Define precedence: module-level final report wins. |
| GUI status and CLI audit diverge | Mirror final status into `toolkit_build_report.json` and add parity tests. |
| Report shape becomes too broad | Use a compact v1 contract with optional detail fields. |

## Success Criteria

1. Module-level `source_fidelity_report.json` is persisted for accurate-ingest GUI builds.
2. `toolkit_build_report.json`, GUI final status, and CLI publishability agree on source-fidelity status.
3. Publishability audit blocks on `blocked`, permits `unknown` for legacy modules, and respects existing degraded/waiver behavior.
4. Tests prove module-level report precedence over stale benchmark report.
5. No module data is changed by this slice.
