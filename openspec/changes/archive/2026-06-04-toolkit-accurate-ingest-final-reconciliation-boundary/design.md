## Context

Accurate-ingest currently has a strong front and middle pipeline: source text becomes source graph and normalized packet artifacts, those artifacts drive builder blueprint and backstage evidence, and source-enhanced ModuleBuilder receives source-lock context. This change keeps that pipeline intact.

The problem is downstream. After ModuleBuilder has generated module artifacts, build-fidelity diagnostics can still report source preservation blockers. The current packet builder treats all `can_continue_after_build_fidelity(...) == False` outcomes as terminal `status: blocked`, so readiness and finishing never run. This is appropriate for fatal structural failures but not for editorial/source-fidelity disputes.

The `Well_of_Ruin` failure shows the distinction. `Trigger`, `Passive Element`, and `Active Element` were classified as required locations, but they are headings/mechanics. That should trigger final editorial reconciliation, not kill the build before publication checks.

## Goals / Non-Goals

**Goals:**

- Preserve the existing front/middle accurate-ingest pipeline exactly.
- Add a final boundary that classifies post-build blockers before stopping the build.
- Keep fatal structural blockers fail-closed.
- Route editorial/source-fidelity blockers into final reconciliation evidence.
- Persist machine-readable reconciliation brief/report artifacts.
- Let accepted final reconciliation satisfy publication status without claiming clean source fidelity.
- Keep this first boundary change provider-free and testable with injected/fixture reconciliation reports.

**Non-Goals:**

- Do not add live LLM Builder patch generation in this change.
- Do not rewrite source graph extraction or blueprint generation.
- Do not mutate source artifacts to hide source-fidelity problems.
- Do not allow invalid JSON, schema failures, or publishability failures to pass.
- Do not change runtime gameplay mode behavior.

## Decisions

### Decision 1: Add a final blocker classifier after build-fidelity reporting

Contract Layer (MUST): the packet builder MUST distinguish fatal blockers from editorial blockers before setting a terminal blocked state.

Guidance Layer (SHOULD): implement this as a small utility, likely `utils/toolkit_final_blocker_classifier.py`, instead of embedding classification rules directly in the route or packet builder.

Rationale: classification is the missing boundary. It lets source-fidelity diagnostics remain visible without giving every diagnostic absolute veto power.

Alternative considered: weaken `can_continue_after_build_fidelity()` globally. Rejected because some fidelity failures represent real structural loss and must still fail closed.

### Decision 2: Keep final reconciliation provider-free in this change

Contract Layer (MUST): this change MUST only add boundary/status plumbing and deterministic artifacts. Live LLM Builder final editing MUST be implemented in a later change.

Guidance Layer (SHOULD): tests may inject accepted reconciliation reports to prove publication semantics before provider-backed editing exists.

Rationale: separating the boundary from the LLM editor reduces risk and keeps the first implementation deterministic.

Alternative considered: implement the final LLM editor immediately. Rejected because it mixes status semantics, artifact contracts, provider handling, patch validation, and retry behavior into one large change.

### Decision 3: Preserve honest source-fidelity reporting

Contract Layer (MUST): accepted reconciliation MUST NOT rewrite blocked source fidelity as clean pass. The system MUST expose a separate effective status such as `reconciled_degraded`.

Guidance Layer (SHOULD): GUI and reports should use language like `Playable publication: pass` and `Source fidelity: reconciled/degraded`.

Rationale: playability and source faithfulness are related but distinct product outcomes.

Alternative considered: automatically downgrade blocked source fidelity to degraded. Rejected because it loses audit trail and makes report disagreement harder to diagnose.

### Decision 4: Final report agreement consumes reconciliation metadata

Contract Layer (MUST): report agreement and publishability composition MUST allow playable publication only when accepted final reconciliation exists and all deterministic publication gates pass.

Guidance Layer (SHOULD): update `utils/toolkit_report_agreement.py` with explicit fields instead of inferring acceptance from freeform notes.

Rationale: report agreement is the final status source for the GUI and module report surfaces.

Alternative considered: bypass report agreement for reconciled modules. Rejected because it would make the GUI and CLI disagree.

## Risks / Trade-offs

- Risk: Editorial blockers could be misclassified and allowed too far. Mitigation: fatal classes remain fail-closed, accepted reconciliation is required, and validation/readiness/publishability still run.
- Risk: Users may confuse playable publication with clean source fidelity. Mitigation: GUI/report language must show both statuses separately.
- Risk: Provider-backed reconciliation is not available in this first change. Mitigation: this change only creates the boundary and can still block without accepted reconciliation; live LLM Builder editing follows in the next change.
- Risk: Existing tests/specs assume blocked source fidelity always blocks publication. Mitigation: update only the relevant requirements with an explicit reconciliation exception.

## Migration Plan

1. Add classifier and reconciliation artifact helpers with provider-free tests.
2. Wire the packet builder to classify blockers after build-fidelity reporting.
3. Persist brief/report artifacts in the workspace.
4. Update report-agreement and GUI status semantics.
5. Verify Well-like bogus heading blockers route to reconciliation-required status instead of immediate terminal build failure.
6. Keep source-fidelity blockers terminal when accepted reconciliation is absent.

Rollback strategy:

- Disable or remove final reconciliation acceptance handling and restore direct `can_continue_after_build_fidelity()` blocking behavior.
- Existing build-fidelity reports and source-fidelity reports remain compatible because this change is additive to artifacts.

## Open Questions

- Should accepted reconciliation be recorded only in the workspace, or mirrored into module-level `toolkit_build_report.json` during finisher refresh? Recommended: both, with workspace as source of the decision and module report as final status surface.
- Should final reconciliation be triggered for all editorial blockers or only when at least one fatal blocker is absent? Recommended: trigger only when fatal blockers are absent.
