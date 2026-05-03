## Context

The toolkit currently has two module-authoring entry paths that share the upstream `ModuleBuilder` but diverge after raw generation.

The newer uploader path in `web/routes/toolkit_homebrew_routes.py` runs:

1. strict source ingest/preflight,
2. normalization and review packet generation,
3. packet-driven `ModuleBuilder` execution,
4. `run_toolkit_homebrew_readiness_gate(...)`,
5. shared toolkit finisher via `refresh_toolkit_build_report(...)`.

The older Describe your Adventure path in `web/web_interface.py` runs:

1. direct narrative prompt collection,
2. direct `ModuleBuilder.build_module(narrative)`,
3. shared toolkit finisher via `run_toolkit_module_postbuild_finishing(...)`.

The finisher is now publication-facing and source-aware. It writes `toolkit_build_report.json`, enriches continuity/semantic authority, runs monster materialization, runs LLM classification, and calls `audit_module_publishability(..., source="toolkit")`. However, the finisher is not the same as the uploader readiness convergence gate. The legacy builder therefore bypasses the bounded validator/repair/revalidation loop that can fix deterministic structural debt before final publishability.

The design target is not to make the legacy builder pretend to be an uploaded source. It is to make both toolkit-produced modules share the same post-builder readiness and finishing contract, while preserving source-specific front-half behavior.

## Goals / Non-Goals

**Goals:**

- Legacy Describe your Adventure builds MUST run readiness convergence before final finishing.
- Uploader packet builds MUST keep their current validation/repair/finishing behavior.
- Both toolkit sources MUST use toolkit-source provenance semantics, not watcher sidecar semantics.
- Readiness, finishing, and publishability outcomes MUST be represented distinctly in status payloads and persisted reports.
- The implementation MUST keep `web/web_interface.py` as a thin host hook and move reusable pipeline logic into extension/helper modules.
- The system MUST fail closed when raw generation succeeds but readiness cannot complete.
- The UI MUST show enough stage detail for a facilitator to tell whether the failure happened in raw generation, readiness convergence, finishing, or publishability.

**Non-Goals:**

- Do not run direct legacy narrative prompts through Homebrew upload preflight, normalization, review packet generation, or source-rights classification.
- Do not require legacy builder runs to create watcher ingest sidecars.
- Do not loosen schema, gameplay, continuity, semantic, media, or publishability rules.
- Do not make sidebar/module-list rendering run live audits.
- Do not refactor the entire Module Builder UI or replace the existing socket transport.
- Do not add provider-backed media generation to this path; media-only debt remains a manual MMG handoff.

## Decisions

### Decision 1: Add A Shared Toolkit Readiness Adapter

Create a shared readiness adapter that can be called by both the uploader build job and the legacy builder socket path.

The adapter MUST accept a toolkit module slug and enough metadata to persist auditable readiness artifacts. It SHOULD live in an extension module, either by extending `web/extensions/toolkit_homebrew_readiness_gate.py` or by adding a small companion such as `web/extensions/toolkit_builder_readiness_adapter.py`.

Recommended public shape:

```python
def run_toolkit_builder_readiness_gate(
    module_slug: str,
    *,
    source_workflow: str,
    build_result: Optional[Dict[str, Any]] = None,
    artifact_workspace: Optional[Path] = None,
    state_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    ...
```

Rationale:

- The existing uploader readiness gate is valuable but workspace-coupled.
- The legacy builder lacks a normalized packet workspace, but it still has a module slug and a raw-build result.
- A wrapper keeps the existing uploader logic intact while making readiness convergence source-neutral after raw builder completion.

Alternatives considered:

- Call `run_toolkit_homebrew_readiness_gate(...)` directly from `web_interface.py` by creating fake uploader workspaces inline. Rejected because it would put artifact-shaping logic in a host file and blur uploader-only concepts into the legacy UI transport.
- Move all legacy builder input through the uploader packet pipeline. Rejected because Describe your Adventure is already a direct narrative builder workflow and should not require source preflight or review packet semantics.
- Do nothing because finisher already runs publishability. Rejected because publishability reports failures but does not perform the uploader readiness convergence loop before finishing.

### Decision 2: Reuse The Existing Convergence Engine Rather Than Duplicate Repairers

The adapter MUST reuse the existing readiness validation, deterministic repair, semantic repair, and structural readiness audit behavior. It MUST NOT duplicate repair implementation in `web_interface.py` or a second builder-only repair loop.

Rationale:

- The uploader readiness gate already carries the current convergence policy.
- Duplicating repair logic would quickly diverge and recreate the exact parity problem this change fixes.

Implementation guidance:

- Factor workspace-independent internals from `run_toolkit_homebrew_readiness_gate(...)` if needed.
- Keep private repair helpers private if practical, but expose one stable adapter entrypoint for toolkit builder flows.
- Persist the same core fields in legacy-builder readiness output: `validation`, `readiness_audit`, `repair_attempts`, `deterministic_passes`, `semantic_passes`, `convergence_outcome`, `fixed_point_detected`, `residual_blocker_classes`, `ready_for_finishing`.

### Decision 3: Use Toolkit-Native Provenance For Legacy Builder Runs

Legacy builder readiness MUST use `source="toolkit"` semantics. It MUST NOT require `homebrew_sidecar_audit.py` watcher sidecars.

The readiness adapter SHOULD persist one or both of these artifact classes:

- `modules/<slug>/toolkit_build_report.json` pre-readiness marker or final report through the finisher path,
- a legacy builder artifact directory or compact JSON files carrying raw build/readiness metadata.

If a compact artifact path is used, it SHOULD include:

- `build_result` with `build_mode: "legacy_builder_narrative_v1"`,
- `module_name`,
- `output_directory`,
- `started_at`/`completed_at`,
- `readiness_validation_report`,
- `readiness_audit_report`,
- `repair_report` or equivalent fields.

Rationale:

- `audit_module_readiness(..., source="toolkit")` already accepts toolkit-native provenance via `toolkit_build_report.json`.
- The finisher currently writes a pre-publishability report before publishability so toolkit-source readiness can self-validate.
- The legacy path needs an equivalent non-stale provenance story for readiness and later sidebar/report consumers.

### Decision 4: Sequence Must Be Raw Build -> Readiness -> Finisher

The legacy builder MUST use this sequence:

1. raw `ModuleBuilder.build_module(...)`,
2. readiness convergence,
3. shared finisher/publishability.

If step 1 fails, stop with raw-generation failure.
If step 2 fails, stop with readiness failure and do not run the final finisher.
If step 3 fails, report finishing/publishability failure with the finisher report.

Rationale:

- This matches uploader behavior: finisher is reached only after readiness says `ready_for_finishing`.
- It prevents the finisher from becoming an accidental substitute for readiness repair.

### Decision 5: UI Progress Should Expose Phase Boundaries

The legacy builder progress UI MUST distinguish at least these phases:

- `raw_generation`,
- `readiness_validation`,
- `readiness_repair`,
- `readiness_audit`,
- `post_build_finishing`,
- `publishability_audit`.

The current 10-stage progress list can remain, but status messages and final payloads MUST expose the actual phase boundary. The UI SHOULD add a hydration/remediation-aware failure detail view using existing helper functions where possible.

Rationale:

- Operators need to know whether they should retry generation, inspect deterministic repair failures, run MMG, or fix semantic blockers.
- The uploader UI already distinguishes more states; the older builder should at least report equivalent final outcomes.

### Decision 6: Report Freshness Remains Persisted-Report Driven

Sidebar/module-list consumers MUST continue reading persisted reports only. They MUST NOT call readiness or publishability live during module list rendering.

The implementation MUST ensure that any builder run that changes module files also refreshes or invalidates report freshness explicitly. A failed readiness run MUST NOT leave a stale previous `toolkit_build_report.json` looking current for the newly generated module state.

Rationale:

- Existing specs require sidebar consumers to avoid live audits.
- Freshness metadata is the guard against stale report state.

## Risks / Trade-offs

### Risk: Workspace Coupling In The Existing Readiness Gate

The uploader readiness gate currently expects workspace artifact files.

Mitigation:

- Factor a module-slug-centric core readiness function and keep workspace persistence as an adapter layer.
- Alternatively, create a minimal legacy-builder workspace under a toolkit artifact root, but do so in the shared adapter, not in `web_interface.py`.

### Risk: Legacy Builder Becomes Stricter And More Builds Stop Earlier

Some modules that previously reached finisher may now stop at readiness.

Mitigation:

- Treat this as intended fail-closed behavior.
- Surface detailed readiness diagnostics and repair reports so the user knows what changed.

### Risk: Stale Reports From Previous Runs

A module regenerated with the same slug could inherit an old `toolkit_build_report.json` until final finishing writes a new report.

Mitigation:

- Write a pre-readiness or readiness-running marker with non-current freshness before validation begins.
- Finalize the report only after readiness and finishing complete.
- If readiness fails, persist a report or artifact that explicitly marks readiness failure and prevents stale success display.

### Risk: Duplicate Pipeline Code

Creating a separate legacy readiness pipeline could diverge from uploader behavior.

Mitigation:

- Require source tests proving both paths import/use the same readiness adapter or factored core.
- Keep one convergence implementation.

### Risk: UI Confusion Between Media Handoff And Failure

Media-only debt should not look like raw build failure, but mixed media+semantic blockers must still fail.

Mitigation:

- Preserve existing finisher media-handoff classification.
- Add tests for media-only, semantic-only, and mixed failure display text.

## Migration Plan

1. Add shared readiness adapter around existing readiness convergence behavior.
2. Update uploader route only as needed to consume the adapter or factored core without behavior change.
3. Update legacy `simulate_build_process(...)` to emit readiness progress and call the adapter after raw generation.
4. Gate finisher execution on `ready_for_finishing`.
5. Update builder UI result/error formatting to show readiness and finishing phases distinctly.
6. Update stale `publication_parity_note` copy.
7. Add regression/source-contract tests for both paths.
8. Run targeted tests and OpenSpec validation.

Rollback strategy:

- The change should be structured so the legacy builder hook can be reverted to direct finisher invocation if a blocker appears.
- The shared readiness adapter should not alter uploader behavior unless explicitly called by uploader routes.
- Any persisted readiness artifacts should be additive and safe to ignore by older code.

## Open Questions

- Should legacy builder readiness artifacts live inside a transient `user_uploads/toolkit/...` workspace for artifact parity, or under a module-local path such as `modules/<slug>/toolkit_readiness_report.json`?
- Should readiness failure write `toolkit_build_report.json` directly, or a separate readiness artifact plus a stale/degraded build report marker?
- Should the UI add a dedicated readiness failure panel now, or reuse the existing JSON build report block for the first implementation?
- Should a raw-generation overwrite of an existing module explicitly clear stale report files before readiness begins, or mark them stale via a new freshness phase?
