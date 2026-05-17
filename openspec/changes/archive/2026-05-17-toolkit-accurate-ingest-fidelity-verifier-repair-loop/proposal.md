## Why

Phase 1 established deterministic `source_manifest.json` and `source_graph.json` artifacts. Phase 2 added section-bounded extraction, identity adjudication, plot topology synthesis, and source-graph-backed `normalized_packet.json` generation. The remaining fidelity risk is that the generated packet can still omit or distort required source truth, and there is no adversarial check that compares source artifacts against the packet before the build path consumes it.

The next accurate-ingest slice should add a normalization fidelity verifier and bounded repair loop. Python should compare source graph, identity, and topology artifacts against `normalized_packet.json`, produce a reviewable fidelity report, and optionally run bounded repair attempts that patch only the normalized packet. The repair loop must remain evidence-bound: LLMs may propose missing packet content, but Python validates every proposal against source refs and existing packet compatibility before persisting it.

## What Changes

- Add a deterministic fidelity audit that compares source artifacts against `normalized_packet.json`.
- Persist `normalization_fidelity_report.json` with coverage, omissions, distortions, unsupported additions, and severity rollups.
- Add a bounded repair loop that proposes and applies review-compatible packet patches for repairable fidelity gaps.
- Persist per-attempt repair artifacts so every repair remains inspectable and reproducible.
- Add final report fields to `normalization_report.json` so readiness can distinguish clean, degraded, repaired, and failed fidelity outcomes.
- Preserve legacy fallback and do not modify Module Builder handoff yet.

## Capabilities

### New Capabilities

- `toolkit-normalization-fidelity-audit`: Normalized packets can be audited against source graph, identity, and topology artifacts before builder handoff.
- `toolkit-normalization-repair-loop`: Repairable packet omissions can be patched through bounded, evidence-backed repair attempts.
- `toolkit-fidelity-reporting`: Normalization reports and workspace artifacts can surface fidelity status without requiring a review UI.

## Non-Goals

- Do not implement builder blueprint generation in this change.
- Do not modify `ModuleBuilder` or `ModuleGenerator` in this change.
- Do not add build-time fidelity gates in this change.
- Do not add the review UI fidelity panel in this change.
- Do not add narrative enrichment in this change.
- Do not remove the legacy one-shot normalizer fallback.
- Do not silently auto-publish repaired packets; repaired output remains reviewable.

## Impact

- **Affected code, later implementation:** `utils/toolkit_normalization_fidelity.py` (new), `utils/toolkit_homebrew_normalizer.py`, `utils/toolkit_homebrew_upload_contract.py`, `utils/toolkit_source_graph_synthesis.py` if shared source-ref helpers are needed, new prompt/test files.
- **Runtime behavior, later implementation:** Normalization-required readable uploads will receive a fidelity audit after packet synthesis. If enabled and safe, bounded repair attempts may improve the packet before final persistence.
- **Backward compatibility:** Existing packet validation and review behavior must remain valid. Workspaces missing multipass artifacts must either skip fidelity audit with degraded status or use legacy compatibility checks.
- **SP/MP compatibility:** Toolkit-only change; no direct tabletop runtime gameplay behavior change.

## Rollout and Fallback

- Fidelity audit should be feature-flagged or fail-safe during implementation.
- If source artifacts are missing, the normalizer must preserve the packet and report that fidelity audit could not run.
- If repair fails, the original packet and all source artifacts must remain available.
- If a repair patch cannot be validated against source evidence, it must be rejected and recorded, not applied.
- Provider failures in repair attempts must be observable and must not silently mark fidelity as clean.

## Review Notes

This change is intentionally the third accurate-ingest slice. It verifies and repairs the normalized packet only. Builder blueprint handoff, build-time gates, review UI, and enrichment remain future phases in `plans/accurate-ingest.md`.
