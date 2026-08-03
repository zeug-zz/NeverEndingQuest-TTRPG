# Step 6.1 Evidence: Well of Ruin bogus-atom regression coverage

**Date:** 2026-06-12
**Step:** 6.1
**OpenSpec change:** `toolkit-accurate-ingest-llm-builder-final-editor`
**Spec:** `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-bogus-source-atom-cleanup/spec.md`

## What was proved

The spec scenario for `accurate-ingest-bogus-source-atom-cleanup` requires:

> **GIVEN** blockers include required locations named `Trigger`,
> `Passive Element`, and `Active Element`
> **AND** source evidence shows those names are trap mechanics headings
> rather than playable locations
> **WHEN** final reconciliation is accepted
> **THEN** those names SHALL NOT remain required final module locations
> **AND** they MAY be dropped as bogus structure or preserved as
> mechanics, trap rules, hazard instructions, plot notes, or DM guidance.

Step 6.1 lands provider-free regression coverage at three layers:

1. **Decision-level proof** -- the accepted patch plan / accepted
   report `decisions` list classifies each of the three trap headings
   with a non-playable decision type drawn from
   `{delete_bogus_atom, reclassify_atom, merge_into_existing,
   preserve_as_dm_guidance, refuse}`. The forbidden
   `create_missing_real_element` decision type is asserted absent for
   the three specific headings.
2. **Module-level proof** -- applying an empty-`file_patches` accepted
   plan to a synthetic Well-of-Ruin module leaves the canonical
   playable-location lists in `areas/*_BU.json`, `map_*.json`, and
   `module_context.json` free of the three trap-heading names.
3. **On-disk / build-metadata proof** -- the persisted
   `final_reconciliation_report.json` (the artifact the build pipeline
   reads) does not classify the three trap headings as final playable
   locations, the persisted `changed_files` list is empty (the
   spec-aligned drop / preserve path requires no module file edits),
   and the accepted report's canonical 12-key top-level shape does not
   register any of the three headings as a top-level field name.

## Files added

- `scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py` (NEW,
  provider-free, 17 tests across 5 classes; per-test tempdir for the
  synthetic Well-of-Ruin-style module; no production module is created
  or touched).

## Files modified

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  (Step 6.1 check + evidence; 6.2/6.3/6.4 and Section 7 left untouched).

No production code was changed by this step. The test file uses the
existing production helpers `validate_final_reconciliation_patch_contract`,
`build_accepted_final_reconciliation_report`,
`apply_final_reconciliation_patch_plan`,
`persist_accepted_final_reconciliation_report`, and
`is_final_reconciliation_accepted` with synthetic inputs.

## Synthetic fixture approach

The synthetic Well-of-Ruin-style module is a 4-location fixture with
the four authored playable locations
(`Rusted Bridge`, `Crumbling Stairwell`, `Rotting Library`,
`Sealed Vault Door`) and none of the three trap headings. The fixture
is written by `_write_synthetic_well_module(module_dir)` into a
per-test tempdir and torn down in `tearDown`.

The fixture is the only place the test reads from disk; the helper
`_collect_playable_location_names_from_module_dir(module_dir)` is a
test-local, read-only, pure function that aggregates playable
location names and ids from `areas/*_BU.json`, `map_*.json`
(non-BU), and `module_context.json`. The helper is not added to
production because no production code currently needs this check
(the production code path is the accepted report / patch plan
decisions, not the on-disk location list).

## Exact proof the three names are not final required locations

### Test 1: every decision for the three headings is in the non-playable allowlist

```
TestStep61AcceptedPatchPlanClassifiesBogusAtomsAsNonPlayable.
test_all_decisions_for_three_headings_are_in_non_playable_allowlist
TestStep61AcceptedPatchPlanClassifiesBogusAtomsAsNonPlayable.
test_no_decision_for_three_headings_uses_create_missing_real_element
```

The accepted plan's three decisions (one per trap heading) all use
either `delete_bogus_atom` or `preserve_as_dm_guidance`; none use
`create_missing_real_element`. The plan validates against
`validate_final_reconciliation_patch_contract` (the contract helper
allows the chosen decision types; it does not yet forbid
`create_missing_real_element` for the three specific headings --
that promotion prevention is owned by Step 6.2).

### Test 2: accepted report decisions are also non-playable for the three headings

```
TestStep61AcceptedReportExcludesBogusAtomsAsPlayableLocations.
test_accepted_report_decisions_never_create_playable_location_for_three_headings
TestStep61AcceptedReportExcludesBogusAtomsAsPlayableLocations.
test_accepted_report_may_preserve_three_headings_as_dm_guidance
TestStep61AcceptedReportExcludesBogusAtomsAsPlayableLocations.
test_accepted_report_changed_files_empty_for_bogus_atom_drop
```

The built accepted report (via `build_accepted_final_reconciliation_report`)
carries the same non-playable decisions through unchanged. The
report's `changed_files` is empty (the spec-aligned drop / preserve
path does not require editing any canonical module file). The
allowed `preserve_as_dm_guidance` path is exercised for `Passive
Element` and `Active Element`.

### Test 3: applying the empty-file_patches plan leaves the synthetic module's playable locations unchanged

```
TestStep61ApplyDoesNotIntroduceBogusAtomsAsLocations.
test_empty_file_patches_apply_does_not_modify_module_locations
```

After running `apply_final_reconciliation_patch_plan(plan, brief)` on
the synthetic module, the helper
`_collect_playable_location_names_from_module_dir(module_dir)` returns
exactly the four authored playable locations and none of the three
trap headings. The slugified variants
(`Passive_Element`, `Active_Element`) are also absent as
`location_id` strings.

### Test 4: the on-disk `final_reconciliation_report.json` carries the same invariant

```
TestStep61PersistedReportExcludesBogusAtomsAsPlayableLocations.
test_persisted_report_decisions_exclude_three_headings_as_playable
TestStep61PersistedReportExcludesBogusAtomsAsPlayableLocations.
test_persister_does_not_modify_module_playable_locations
```

The persisted report writes successfully, passes the legacy
acceptance oracle, and locks
`source_fidelity_effective_status="reconciled_degraded"`. The
persister does not modify the module's playable location list across
the persist call (pre/post `_collect_playable_location_names_from_module_dir`
output is equal).

### Test 5: build-metadata shape does not register the three headings as fields or values

```
TestStep61BuildResultMetadataExcludesBogusAtomsAsLocations.
test_accepted_metadata_shape_does_not_carry_three_headings
TestStep61BuildResultMetadataExcludesBogusAtomsAsLocations.
test_orchestrator_accepted_patch_plan_is_dotted_through_to_report
```

The accepted report's canonical 12-key top-level shape is pinned
(`version`, `status`, `reconciliation_status`,
`source_fidelity_effective_status`, `playable_publication_candidate`,
`decisions`, `changed_files`, `validation_after_reconciliation`,
`publishability_after_reconciliation`,
`report_agreement_after_reconciliation`, `notes`, `diagnostics`).
None of the three headings is a top-level field name; none is a
`decisions` list entry value. Every plan decision is carried through
the report decision-by-decision so the build pipeline cannot
silently rewrite the three trap headings' classification.

## ASCII compliance

- `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py`
  -> `0 violations`

## Verification commands

```
# Compile new test file
.venv/bin/python -m py_compile scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py
# -> PASS

# Run new test file
.venv/bin/python -m unittest scripts.test_toolkit_step61_well_of_ruin_bogus_atoms -v
# -> 17 PASS, 0 FAIL in 0.010s

# Run related final-reconciliation test suites for regression
.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation
# -> 524 PASS, 0 FAIL in 0.077s (no regression on final-reconciliation runner)

# Run combined related suites (path-safety, legacy final-reconciliation, report agreement, new step 6.1)
.venv/bin/python -m unittest scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_toolkit_step61_well_of_ruin_bogus_atoms
# -> 120 PASS, 0 FAIL in 0.092s

# Run focused Step 4-5 packet-builder / final-editor test classes
.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep43EditorialReconciliationRequired \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep44AcceptedReconciliation \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep45EvidenceReportsImmutability \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep51FinalEditorInvocation \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep53FatalMixedGuard \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestStep54FrontMiddleImmutability \
  scripts.test_toolkit_homebrew_gui_unified_flow.TestFinalReconciliationBoundarySourceContract
# -> 49 PASS, 0 FAIL in 0.139s
# (The 8 pre-existing test errors in TestDescribeBlueprintNotReady and
#  TestPacketBuilderV2Integration are unrelated to this change -- they
#  fail on the clean main branch without the new test file present.
#  Those tests depend on production code references that have shifted
#  across the change series; they are not in scope for Step 6.1.)

# ASCII compliance
python3 scripts/check_ascii_compliance.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py
# -> 0 violations

# OpenSpec strict validation
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
# -> VALID

# Specs validation
openspec validate --specs
# -> 364/364 PASS (no spec regression)
```

## Follow-up

- Step 6.2 will prove that bogus source atoms are either dropped as
  final structure or preserved as mechanics/DM guidance without
  poisoning Narrator-facing topology. The 6.1 tests pin the
  decision-level + on-disk-level invariants; 6.2 will add a
  Narrator-payload-level proof (e.g. the editor-accepted report's
  `decisions` entries never carry `to: playable_location` or
  `to: location` and any preserved DM-guidance text lives in
  `notes` / `dmGuidance` rather than the playable location list).
- Step 6.2 may also want to harden the contract helper to forbid
  `create_missing_real_element` for `from: required_location`
  decisions where the source excerpt shows a trap-mechanics heading
  pattern, but the spec's current wording leaves the LLM / final
  editor with discretion here, so 6.2 will likely stay at the
  payload-projection layer rather than tighten the contract.
- Step 6.3 / 6.4 are still open and untouched by this step.
