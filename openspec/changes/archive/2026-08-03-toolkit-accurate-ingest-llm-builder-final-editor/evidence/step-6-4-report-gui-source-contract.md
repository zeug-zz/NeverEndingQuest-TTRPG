# Step 6.4 - Report/GUI Source-Contract Tests for Separated Axes

## Objective

Prove that the accurate-ingest final reconciliation surfaces keep the
playable_publication axis and the source-fidelity axis as INDEPENDENT
fields end-to-end. The GUI template, the helper conditional, and the
report composer must all distinguish the two axes so:

1. Accepted reconciliation flips `playable_publication_status` to
   `pass` while leaving `source_fidelity_status` at its original
   blocked/degraded value and surfacing `reconciled_degraded` on
   `source_fidelity_effective_status`.
2. Clean source-fidelity pass (no reconciliation) does NOT fire the
   reconciled flag and keeps both axes labelled `pass`.
3. The GUI never implies clean source fidelity when only an accepted
   reconciliation exists.

## Production State (unchanged by this step)

- `web/templates/module_toolkit.html` (lines ~6490-6575):
  - `isFinalReconciledPlayable(payload)` helper requires all four
    axes simultaneously: `final_reconciliation_accepted === true`
    AND `source_fidelity_reconciled === true` AND
    `source_fidelity_effective_status === 'reconciled_degraded'` AND
    `playable_publication_status === 'pass'`.
  - `formatReportAgreementSection(rawPayload)` emits `Source Fidelity:`,
    `Source Fidelity Effective:`, `Source Fidelity Reconciled:`,
    `Final Reconciliation:`, and `Playable Publication:` as SEPARATE
    `lines.push(...)` calls.
  - The reconciled success branch ("Build completed after final
    reconciliation...") says "reconciled/degraded" and "not clean
    pass" and "Playable publication candidate".
  - The generic failure branches ("Build Blocked - Fidelity Check
    Failed", "Not Publishable") remain for non-reconciled cases.
- `utils/toolkit_report_agreement.py`:
  - `compose_report_agreement(...)` returns a dict with the two
    axes as independent keys: `playable_publication_status` and
    `source_fidelity_status` (and effective / reconciled variants).
  - The composer does NOT alias one to the other: the function
    source has no `playable = sf` assignment.

## Test Additions

### Augmented `TestStep64ReconciledDegradedWording` (18 new tests, 26 total)

In `scripts/test_toolkit_module_build_publication_parity.py`. New
helper `_extract_helper_block` and `_extract_formatter_block` locate
the JS bodies of `isFinalReconciledPlayable` and
`formatReportAgreementSection` so source-contract assertions can
inspect the actual conditional and the actual `lines.push(...)` calls.

Helper conditional pinning (6 tests):

- `test_helper_requires_playable_publication_status_pass`
- `test_helper_requires_source_fidelity_effective_status_reconciled_degraded`
- `test_helper_rejects_clean_pass_source_fidelity_effective` (new)
- `test_helper_requires_final_reconciliation_accepted_true`
- `test_helper_requires_source_fidelity_reconciled_true`
- `test_helper_uses_single_conditional_with_all_four_axes`
- `test_helper_walks_multiple_nested_payload_shapes`

Formatter source-contract (6 tests):

- `test_formatter_emits_source_fidelity_label`
- `test_formatter_emits_source_fidelity_effective_label`
- `test_formatter_emits_playable_publication_label`
- `test_three_axes_are_independent_lines` (new)
- `test_formatter_distinguishes_source_fidelity_from_effective` (new)
- `test_formatter_keeps_final_reconciliation_accepted_distinct` (new)

Reconciled branch negative wording (3 tests):

- `test_reconciled_branch_states_reconciled_degraded_explicitly`
- `test_reconciled_branch_mentions_playable_publication`
- `test_reconciled_branch_no_clean_pass_phrase` (new)

Generic failure copy pinned (2 tests):

- `test_generic_blocked_branch_copy_intact` (new)
- `test_generic_not_publishable_branch_copy_intact` (new)

### New `TestStep64ReportAgreementAxesSeparation` (9 tests)

In `scripts/test_toolkit_module_build_publication_parity.py`. Pure
report-data separation tests against `utils.toolkit_report_agreement`:

- `test_result_dict_has_separate_playable_and_fidelity_keys`
- `test_accepted_recon_playable_pass_does_not_rewrite_source_fidelity`
- `test_clean_pass_keeps_effective_status_pass_no_reconciled_flag`
- `test_degraded_original_with_accepted_recon_axes_remain_separate`
- `test_blocked_without_recon_axes_blocked_separately`
- `test_blocked_effective_status_with_accepted_recon_does_not_pretend_pass`
- `test_playable_and_fidelity_values_can_diverge`
- `test_no_aliasing_or_co_derivation_in_production_source`
- `test_module_dir_accepted_recon_axes_separate_in_real_data`

## Verification

All commands run on 2026-06-12.

```
$ .venv/bin/python -m py_compile scripts/test_toolkit_module_build_publication_parity.py scripts/test_toolkit_report_agreement.py
(no output -> PASS)

$ .venv/bin/python -m unittest -v scripts.test_toolkit_module_build_publication_parity.TestStep64ReconciledDegradedWording
...
Ran 26 tests in 0.005s
OK

$ .venv/bin/python -m unittest -v scripts.test_toolkit_module_build_publication_parity.TestStep64ReportAgreementAxesSeparation
...
Ran 9 tests in 0.003s
OK

$ .venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
...
Ran 162 tests in 0.483s
OK

$ .venv/bin/python -m unittest -q scripts.test_toolkit_report_agreement
...
Ran 32 tests in 0.012s
OK

$ python3 scripts/check_ascii_compliance.py scripts/test_toolkit_module_build_publication_parity.py scripts/test_toolkit_report_agreement.py
ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0 fixed_files=0 fixed_chars=0

$ openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
Change 'toolkit-accurate-ingest-llm-builder-final-editor' is valid
```

## Files Modified

- `scripts/test_toolkit_module_build_publication_parity.py` (+27 tests)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (6.4 checked)

## Production Changes

None. Step 6.4 is test-only.
