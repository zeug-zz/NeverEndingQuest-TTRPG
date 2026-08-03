# Step 5.2: Readiness/Finisher Continuation Gate

**Status:** COMPLETED 2026-06-12

## Objective

Lock the contract that readiness/finisher continuation is allowed ONLY when
final reconciliation is accepted AND the deterministic gates (schema
validation, readiness, publishability, report agreement) have passed. The
existing production code already satisfies this contract via the
``build_status == "success"`` gate in the route layer plus the packet
builder's accepted-path semantics plus the finisher's
``is_final_reconciliation_accepted`` oracle on the persisted
``final_reconciliation_report.json``. Per the task constraint, this step
adds ONLY minimal source-contract tests and a clarifying comment --
runtime widening was not needed.

## Files Changed

### Production Code (comments only, no behavior change)

- ``web/routes/toolkit_homebrew_routes.py``
  - Added a short clarifying comment block above the
    ``if build_status == "success":`` branch in the build handler (around
    line 1487-1504) that documents the Step 5.2 gate contract:
    - Editorial + editor accepted + persist success -> "success" with
      ``final_reconciliation_accepted=True`` and
      ``source_fidelity_effective_status="reconciled_degraded"`` (the only
      accepted metadata shape that may flow to readiness/finisher).
    - Editorial + editor non-accepted or persist fail -> "blocked" (handled
      in the build_status == "blocked" branch above; never reaches here).
    - Editorial + helper API import fail -> "final_reconciliation_required"
      (handled in the branch above; never reaches here).
    - Fatal / mixed / unknown fidelity classification -> "blocked"
      (handled in the branch above; never reaches here).

- ``web/extensions/toolkit_homebrew_packet_builder.py``
  - Added short clarifying comments inside ``_invoke_final_editor_or_fallback``
    documenting:
    - On the accepted path: the helper does NOT mutate
      ``build_result["status"]``; the status remains "success" so the
      route layer's success branch launches readiness/finisher; the
      finisher will load the persisted accepted report from ``module_dir``
      via the legacy ``is_final_reconciliation_accepted`` oracle.
    - On the else (non-accepted / fallback) path: the helper mutates
      ``build_result["status"]`` to either "blocked" (non-accepted or
      persist fail) or "final_reconciliation_required" (legacy fallback).
      In neither sub-path does the build reach readiness/finisher.

  No code logic was changed. The accepted / blocked / required paths
  were already producing the right status; the comments just document the
  contract so future maintainers do not silently widen the gate.

### Tests

- ``scripts/test_toolkit_module_build_publication_parity.py``
  - Added new test class ``TestStep52ReadinessFinisherGate`` (12 tests,
    all provider-free and source-contract based; one end-to-end
    finisher test):
    1. ``test_route_layer_has_blocked_branch`` - ``build_status ==
       "blocked"`` branch lives BEFORE the success branch.
    2. ``test_route_layer_has_final_reconciliation_required_branch`` -
       ``build_status == "final_reconciliation_required"`` branch lives
       BEFORE the success branch.
    3. ``test_route_layer_success_branch_launches_readiness_then_finisher``
       - Both ``_run_homebrew_readiness_gate`` and
       ``_run_homebrew_finisher`` invocations live INSIDE the
       ``build_status == "success"`` block, and finisher runs AFTER
       readiness.
    4. ``test_route_layer_has_explicit_step52_gate_comment`` - the route
       layer carries the explicit Step 5.2 gate comment.
    5. ``test_packet_builder_editor_accepted_keeps_status_success`` - the
       accepted path in the packet builder does NOT mutate
       ``build_result["status"]`` to "blocked" or
       "final_reconciliation_required"; sets the accepted metadata.
    6. ``test_packet_builder_helper_blocked_path_returns_early`` - the
       helper's blocked sub-path returns early so the build does not
       reach normal persistence.
    7. ``test_packet_builder_status_blocked_does_not_reach_normal_persistence``
       - blocked return path appears BEFORE the normal
       ``build_result_persisted`` call.
    8. ``test_packet_builder_source_fidelity_honesty_never_claims_clean_pass``
       - accepted branch never assigns clean-pass variants
       ("pass" / "clean_pass" / "clean" / "source_fidelity_pass").
    9. ``test_finisher_loads_accepted_final_reconciliation_report_from_module_dir``
       - finisher imports the helper API, calls it on ``module_dir``, and
       forwards the accepted metadata into ``compose_report_agreement(...)``.
    10. ``test_finisher_never_assigns_clean_pass_in_source_fidelity_effective``
        - finisher never hard-assigns
        ``source_fidelity_effective_status = "pass"``.
    11. ``test_finisher_uses_persisted_report_not_build_result_flag`` -
        finisher sources ``final_rec_accepted`` ONLY from the legacy
        oracle's verdict on the persisted report; NEVER from a top-level
        ``build_result.get(...)`` flag (Step 5.2 contract: the report
        agreement is tied to the persisted report, not a build_result
        flag).
    12. ``test_finisher_consumes_accepted_report_in_actual_run`` - end-to-end
        behavior: with an accepted
        ``final_reconciliation_report.json`` on disk, the finisher
        surfaces ``final_reconciliation_accepted=True`` and
        ``source_fidelity_effective_status="reconciled_degraded"`` in
        the result (even when raw ``source_fidelity_status`` was
        "blocked").

## Gate Proven

The Step 5.2 gate is proven by the combination of:

1. **Route layer ordering:** ``build_status == "blocked"`` and
   ``build_status == "final_reconciliation_required"`` branches live
   BEFORE the success branch and return early; readiness/finisher only
   run inside the success branch.

2. **Packet builder accepted-path semantics:** the editor-accepted +
   persist-success path leaves ``build_result["status"] == "success"``
   and attaches the accepted metadata
   (``final_reconciliation_accepted=True``,
   ``source_fidelity_effective_status="reconciled_degraded"``). The
   helper does NOT mutate the status to "blocked" or
   "final_reconciliation_required" on the accepted path.

3. **Packet builder non-accepted path semantics:** the helper mutates
   ``build_result["status"]`` to "blocked" (non-accepted or persist
   fail) or "final_reconciliation_required" (legacy fallback), and the
   non-blocked return path either returns early (blocked) or leaves the
   build in a paused state that the route layer handles at a dedicated
   branch.

4. **Finisher consumes the persisted report (not a build_result flag):**
   the finisher's report-agreement stage loads
   ``final_reconciliation_report.json`` from ``module_dir`` via the
   legacy ``is_final_reconciliation_accepted`` oracle, and forwards the
   accepted metadata into ``compose_report_agreement(...)``. The
   finisher does NOT source ``final_rec_accepted`` from a top-level
   ``build_result.get(...)`` flag.

5. **Source-fidelity honesty:** the accepted path never claims clean
   pass; the finisher never hard-assigns
   ``source_fidelity_effective_status = "pass"``.

## Verification

- ``.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py scripts/test_toolkit_module_build_publication_parity.py`` -> PASS
- ``.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity.TestStep52ReadinessFinisherGate -v`` -> **12 PASS, 0 FAIL**
- ``.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity`` -> **135 PASS, 0 FAIL** (was 123 before Step 5.2; +12 new tests)
- ``.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep42FatalBlockedBehavior scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch`` -> 35 PASS, 0 FAIL (no regression on prior step 4.x / 5.1 tests)
- ``.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation`` -> 524 PASS, 0 FAIL (no regression on final-reconciliation runner)
- ``python3 scripts/check_ascii_compliance.py web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py scripts/test_toolkit_module_build_publication_parity.py`` -> 0 violations
- ``openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict`` -> VALID

## Out of Scope (Step 5.3+)

- Fatal / mixed / unknown classification: the build_status branching
  in the packet builder already routes these to the blocked branch
  before reaching the success branch. Step 5.3 will deepen this
  contract with explicit source-contract tests.
- Front/middle pipeline artifacts: untouched.
- The 8 pre-existing errors in
  ``scripts.test_toolkit_homebrew_gui_unified_flow`` (in
  ``TestDescribeBlueprintNotReady`` and
  ``TestPacketBuilderV2Integration``) are pre-existing failures from
  earlier steps and are NOT caused by Step 5.2 changes. The 2 FAILs
  that were present earlier (the "no reconciliation" source-contract
  tests) were triggered by the literal filename strings in my comment
  and have been fixed by removing the literal strings (the comment now
  describes the behavior in prose).
