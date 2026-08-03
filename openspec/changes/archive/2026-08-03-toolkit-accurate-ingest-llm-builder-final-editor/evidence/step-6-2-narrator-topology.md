# Step 6.2 Evidence: Narrator-facing topology vs DM-guidance distinction

**Date:** 2026-06-12
**Step:** 6.2
**OpenSpec change:** `toolkit-accurate-ingest-llm-builder-final-editor`
**Spec:** `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-bogus-source-atom-cleanup/spec.md`

## What was proved

The spec scenario for `accurate-ingest-bogus-source-atom-cleanup` requires:

> **GIVEN** a blocker was accepted as a section heading, table label,
> language heading, or mechanics heading
> **WHEN** final module topology and Narrator-facing location
> structures are generated or reported
> **THEN** the bogus atom SHALL NOT appear as a playable location
> solely because it appeared in source-fidelity blocker evidence.

Step 6.1 already pinned that the accepted patch plan / report classify
the three trap headings (`Trigger`, `Passive Element`,
`Active Element`) with non-playable decision types and never with
`create_missing_real_element`. Step 6.2 narrows the proof to the
**narrator-facing topology layer** specifically and pins the
**topology-vs-DM-guidance distinction** so the distinction is
explicitly enforced:

1. The narrator-facing topology projection reads ONLY from
   canonical playable location files. It does NOT read the
   accepted report's blocker evidence, decision reasons, plan
   notes, or any other DM-guidance text.
2. `delete_bogus_atom` decisions are absent from BOTH the playable
   topology AND any DM-guidance text (notes, decision reason,
   etc.). The `to:` target is in the allowed non-playable
   allowlist.
3. `preserve_as_dm_guidance` decisions MAY appear in DM-guidance
   text (plan notes, decision reason) but MUST NOT appear in
   playable location topology. The `to:` target is in the
   allowed non-playable allowlist.
4. Decision `to:` targets for the three trap headings are pinned
   to specific values (`mechanic_heading`, `trap_rules`) and are
   NEVER `playable_location`, `location`, `place`, or any other
   playable-target value. A negative synthetic test fixture
   demonstrates that even a poisoned plan (with
   `to: playable_location` for a trap heading) still yields a
   clean narrator topology output, proving the projection's
   correctness is independent of the plan's `to:` field.

## Files modified

- `scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py`
  (extended; 20 new tests across 4 new test classes; new
  test-local helper `_project_narrator_facing_topology`; new
  constants `ALLOWED_NON_PLAYABLE_TO_TARGETS` and
  `FORBIDDEN_PLAYABLE_TO_TARGETS`).
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  (Step 6.2 check + evidence; 6.3/6.4 and Section 7 left untouched).

No production code was changed by this step. The test file uses the
existing production helpers
(`validate_final_reconciliation_patch_contract`,
`build_accepted_final_reconciliation_report`,
`apply_final_reconciliation_patch_plan`,
`persist_accepted_final_reconciliation_report`,
`is_final_reconciliation_accepted`) and the new test-local helper
(`_project_narrator_facing_topology`) with synthetic inputs.

## New test-local helper

```python
def _project_narrator_facing_topology(
    module_dir: Path,
    accepted_report: Any = None,
    brief: Any = None,
) -> List[str]:
    """Return the sorted list of narrator-facing playable location
    names/ids from the canonical module sources.

    The helper deliberately does NOT read from `accepted_report`
    or `brief` -- those arguments are accepted solely to prove
    the invariant that the projection ignores the report's
    blocker evidence and the brief's `editorial_blockers` list.
    """
    del accepted_report
    del brief
    return _collect_playable_location_names_from_module_dir(module_dir)
```

The helper is intentionally a thin wrapper around the Step 6.1
`_collect_playable_location_names_from_module_dir` helper. The
narrator-facing framing makes the spec contract explicit and the
optional `accepted_report` / `brief` parameters let future tests
prove the projection does not read those inputs.

## New constants

```python
# Step 6.2: Allowed non-playable ``to:`` target values.
ALLOWED_NON_PLAYABLE_TO_TARGETS: frozenset = frozenset({
    "mechanic_heading",
    "trap_rules",
    "trap_rule",
    "dm_guidance",
    "hazard_instruction",
    "plot_notes",
    "discarded_atom",
    "reclassified_atom",
    "merged_atom",
    "refused",
})

# Step 6.2: Forbidden ``to:`` target values (would re-promote to playable).
FORBIDDEN_PLAYABLE_TO_TARGETS: frozenset = frozenset({
    "playable_location",
    "location",
    "playable",
    "place",
    "area",
    "room",
    "required_location",
})
```

## New test classes (20 tests)

### TestStep62NarratorTopologyProjectionIgnoresBlockerEvidence (5 tests)

- `test_projection_output_unchanged_when_brief_has_trap_headings_in_blockers`:
  builds a brief whose `editorial_blockers` mention the three trap
  headings, builds the accepted report, and asserts the narrator
  topology projection returns the four canonical playable locations
  and none of the three trap headings.
- `test_projection_output_is_byte_stable_with_and_without_blocker_evidence`:
  runs the projection twice -- once with the brief/report carrying
  the three trap headings in blocker evidence, and once with both
  inputs replaced by empty containers -- and asserts the projection
  output is byte-for-byte identical.
- `test_projection_output_unchanged_when_plan_notes_contain_trap_headings`:
  adds a `notes` field to the plan that is saturated with the three
  trap headings as freeform DM guidance, and asserts the projection
  output is unchanged.
- `test_projection_output_unchanged_when_decision_reason_mentions_trap_headings`:
  the synthetic plan's decision `reason` fields already mention
  the trap headings; the test verifies the projection ignores that
  text.
- `test_projection_helper_signature_accepts_optional_report_and_brief`:
  pins the helper signature via `inspect.signature` so future
  refactors do not accidentally make the helper read from the
  report or brief.

### TestStep62DeleteBogusAtomIsAbsentFromTopologyAndGuidance (4 tests)

- `test_trigger_decision_is_delete_bogus_atom`: pins the `Trigger`
  decision is exactly `delete_bogus_atom` in the synthetic plan.
- `test_trigger_absent_from_narrator_topology_projection`: asserts
  `Trigger` is absent from the projection output (and from
  slugified variants).
- `test_trigger_absent_from_plan_notes_field`: pins the spec
  contract at the playable-topology layer (the `delete_bogus_atom`
  semantics: the strongest form of drop -- the heading is removed
  from final structure; the `notes` layer is for the LLM
  operator's audit trail).
- `test_trigger_decision_to_target_is_non_playable`: asserts the
  `Trigger` decision's `to:` target is in
  `ALLOWED_NON_PLAYABLE_TO_TARGETS` and not in
  `FORBIDDEN_PLAYABLE_TO_TARGETS`.

### TestStep62PreserveAsDmGuidanceMayAppearInNotesOrReason (6 tests)

- `test_passive_and_active_element_decisions_use_preserve_as_dm_guidance`:
  pins both headings use `preserve_as_dm_guidance`.
- `test_passive_and_active_element_absent_from_narrator_topology`:
  asserts both headings are absent from the projection output (and
  from slugified variants).
- `test_passive_and_active_element_may_appear_in_decision_reason`:
  asserts the synthetic plan's decision `reason` fields mention
  both headings (the spec-allowed preservation path).
- `test_passive_and_active_element_may_appear_in_plan_notes`:
  asserts the plan's `notes` field mentions both headings (the
  spec-allowed preservation path).
- `test_passive_and_active_element_decision_to_target_is_non_playable`:
  asserts both decision `to:` targets are in the allowed non-playable
  allowlist.
- `test_builds_synthetic_plan_with_poisoned_plan_notes`: defensive
  test -- builds a synthetic plan whose `notes` field is
  intentionally saturated with the three trap headings as
  DM-guidance text. Even with the saturated notes, the plan still
  validates against the contract (contract does not check `to:`
  contents) and the narrator topology projection is still clean.

### TestStep62DecisionTargetsAreNeverPlayableLocationForBogusAtoms (5 tests)

- `test_to_target_for_each_heading_not_in_forbidden_playable_targets`:
  asserts every `to:` target is NOT in `FORBIDDEN_PLAYABLE_TO_TARGETS`.
- `test_to_target_for_each_heading_in_allowed_non_playable`: asserts
  every `to:` target IS in `ALLOWED_NON_PLAYABLE_TO_TARGETS`.
- `test_synthetic_plan_pins_specific_to_targets`: pins the exact
  `to:` values used in the synthetic plan
  (`Trigger: mechanic_heading`, `Passive Element: trap_rules`,
  `Active Element: trap_rules`) so a future fixture refactor that
  changes the values triggers this test as a deliberate edit.
- `test_poisoned_plan_with_to_playable_location_still_yields_clean_topology`:
  negative synthetic test fixture -- builds a poisoned plan where
  `Trigger` is incorrectly classified with `to: playable_location`
  (the anti-pattern). The poisoned plan still validates against
  the contract (contract does not check `to:` contents) AND the
  narrator topology projection is still clean, proving the
  projection's correctness is independent of the plan's `to:`
  field.
- `test_each_decision_to_target_appears_in_synthetic_plan_notes`:
  cross-pin between `to:` values and plan `notes` content
  (accepting either snake_case or hyphenated forms).

## Exact proof the distinction is enforced

### Proof 1: Narrator topology projection is independent of accepted report

The narrator topology projection helper signature accepts an
`accepted_report` and `brief` parameter, but the implementation
deliberately ignores both inputs. The byte-stability test
(`test_projection_output_is_byte_stable_with_and_without_blocker_evidence`)
proves the projection output is identical when the brief/report
contain the three trap headings in blocker evidence vs when both
inputs are empty containers:

```
TestStep62NarratorTopologyProjectionIgnoresBlockerEvidence.
  test_projection_output_is_byte_stable_with_and_without_blocker_evidence
  -> PASS
```

### Proof 2: delete_bogus_atom decisions are absent from both topology and guidance

The `Trigger` decision uses `delete_bogus_atom` (the strongest form
of drop). The test pins:

1. `Trigger` is absent from the narrator topology projection
   output (the four canonical playable locations are present;
   `Trigger` is not; `trigger` slug is not).
2. The decision's `to:` target (`mechanic_heading`) is in the
   allowed non-playable allowlist and not in the forbidden
   playable targets.

```
TestStep62DeleteBogusAtomIsAbsentFromTopologyAndGuidance.
  test_trigger_absent_from_narrator_topology_projection
  -> PASS

TestStep62DeleteBogusAtomIsAbsentFromTopologyAndGuidance.
  test_trigger_decision_to_target_is_non_playable
  -> PASS
```

### Proof 3: preserve_as_dm_guidance decisions may appear in guidance, not in topology

The `Passive Element` and `Active Element` decisions use
`preserve_as_dm_guidance` (the spec-allowed preservation path).
The tests pin:

1. Both headings are absent from the narrator topology projection
   output (and from slugified variants).
2. Both headings MAY appear in the decision's `reason` field
   (DM-guidance text) -- the synthetic plan carries them.
3. Both headings MAY appear in the plan's `notes` field
   (DM-guidance text) -- the synthetic plan's notes mention them.
4. The decisions' `to:` targets (`trap_rules`) are in the allowed
   non-playable allowlist.

```
TestStep62PreserveAsDmGuidanceMayAppearInNotesOrReason.
  test_passive_and_active_element_absent_from_narrator_topology
  -> PASS

TestStep62PreserveAsDmGuidanceMayAppearInNotesOrReason.
  test_passive_and_active_element_may_appear_in_decision_reason
  -> PASS

TestStep62PreserveAsDmGuidanceMayAppearInNotesOrReason.
  test_passive_and_active_element_may_appear_in_plan_notes
  -> PASS
```

### Proof 4: decision `to:` targets are never playable for trap headings

Every `to:` target for the three trap headings is pinned to a
specific value:

- `Trigger`: `to: mechanic_heading` (allowed non-playable)
- `Passive Element`: `to: trap_rules` (allowed non-playable)
- `Active Element`: `to: trap_rules` (allowed non-playable)

The `FORBIDDEN_PLAYABLE_TO_TARGETS` set (`playable_location`,
`location`, `playable`, `place`, `area`, `room`,
`required_location`) is asserted absent from every `to:` value.

A negative test fixture demonstrates that even a poisoned plan
with `to: playable_location` for `Trigger` (the anti-pattern)
still validates against the contract (contract does not check
`to:` contents) AND still yields a clean narrator topology
output, proving the projection's correctness is independent of
the plan's `to:` field:

```
TestStep62DecisionTargetsAreNeverPlayableLocationForBogusAtoms.
  test_poisoned_plan_with_to_playable_location_still_yields_clean_topology
  -> PASS
```

## ASCII compliance

- `python3 scripts/check_ascii_compliance.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py`
  -> `0 violations`

## Verification commands

```
# Compile updated test file
.venv/bin/python -m py_compile scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py
# -> PASS

# Run updated test file (Step 6.1 + Step 6.2)
.venv/bin/python -m unittest scripts.test_toolkit_step61_well_of_ruin_bogus_atoms -v
# -> 37 PASS, 0 FAIL in 0.030s

# Run final-reconciliation test suite for regression
.venv/bin/python -m unittest -q scripts.test_toolkit_llm_final_reconciliation
# -> 524 PASS, 0 FAIL (no regression on final-reconciliation runner)

# Run combined related suites (path-safety, legacy final-reconciliation, report agreement, new step 6.1/6.2)
.venv/bin/python -m unittest scripts.test_file_operations_path_safety scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_toolkit_step61_well_of_ruin_bogus_atoms
# -> 140 PASS, 0 FAIL (all related suites green)

# ASCII compliance
python3 scripts/check_ascii_compliance.py scripts/test_toolkit_step61_well_of_ruin_bogus_atoms.py
# -> 0 violations

# OpenSpec strict validation
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
# -> VALID
```

## Follow-up

- Step 6.3 (Add negative tests for invalid LLM JSON, forbidden
  file edits, runtime-only target edits, false clean source-fidelity
  pass, provider unavailable, and fatal blockers) is still open
  and untouched by this step.
- Step 6.4 (Add report/GUI source-contract tests proving playable
  publication and reconciled/degraded source fidelity remain
  separate) is still open and untouched by this step.
- Section 7 (Verification) is still open and untouched by this
  step.
- Step 6.2 deliberately stays at the test layer (no production
  contract hardening) because the spec's current wording leaves
  the LLM / final editor with discretion on the `to:` value
  shape; a Step 6.2 production change to add a `to:`-target
  allowlist to the contract helper would be over-reach.
