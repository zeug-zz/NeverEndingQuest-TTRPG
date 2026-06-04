# Accurate Ingest Final Reconciliation Plan

**Status:** Draft for review  
**Date:** 2026-06-02  
**Scope:** Final editorial/publication reconciliation only. Do not rewrite the accurate-ingest front or middle pipeline.

## Purpose

The accurate-ingest pipeline is now strong enough to carry source material through source graph extraction, blueprint handoff, backstage audit evidence, and source-enhanced ModuleBuilder generation. The remaining product problem is at the final publication boundary.

Today, final build-fidelity checks can stop a generated module after ModuleBuilder has already produced usable module artifacts. Some blockers are real structural problems. Others are source-classification or source-fidelity artifacts that require editorial judgment, such as treating markdown section headings (`Trigger`, `Passive Element`, `Active Element`) as required locations.

This plan adds a final LLM Builder editorial reconciliation layer. Its job is to review stubborn final blockers, decide whether they are real or bogus, and produce a playable, schema-valid, publishable module. Source fidelity remains visible as evidence, but it should not have absolute veto power over a module that LLM Builder can reconcile into a valid adventure.

## Non-Negotiable Boundary

This plan does not change the front or middle accurate-ingest pipeline.

Keep intact:

- Source manifest and source graph extraction.
- Normalized packet generation.
- Builder blueprint generation.
- Backstage audit evidence and briefing.
- Source-enhanced ModuleBuilder handoff.
- Generator source-lock context injection.
- Existing source-fidelity reports as diagnostic evidence.

Change only the final editorial/publication boundary.

The new responsibility split is:

```text
Front/Middle Pipeline
source markdown
  -> source graph / manifest / normalized packet
  -> builder blueprint / audit evidence / source-lock context
  -> source-enhanced ModuleBuilder
  -> generated module JSON

Final Editorial Pipeline
generated module JSON
  -> deterministic final checks
  -> LLM Builder final reconciliation when blockers exist
  -> deterministic validation/readiness/publishability gates
  -> playable publication if final JSON is valid
```

## Problem Example: Well of Ruin

Input:

- `Local_Docs/modules/hombrew/modules/Well of Ruin.md`

Observed final blocker:

```text
Build fidelity blocked: Required location 'Trigger' not found in module; Required location 'Passive Element' not found in module; Required location 'Active Element' not found in module
```

These terms are source headings/mechanics, not required adventure locations. Treating them as locations creates two problems:

- It kills a build that otherwise produced usable module artifacts.
- It can poison later Builder/Narrator context by implying these terms are actual places that must exist in the module topology.

Correct final reconciliation behavior:

- LLM Builder reviews the blocker evidence and source excerpts.
- LLM Builder determines that these are not locations.
- LLM Builder removes or downgrades them from required-location structures.
- If useful, LLM Builder preserves their meaning as mechanics, trap rules, hazard instructions, plot notes, or DM guidance.
- Python validates the resulting module JSON.
- The module can publish if schema/readiness/publishability pass.

## Core Principle

At the final publication stage, playability takes priority over literal source-fidelity preservation.

This does not mean source-fidelity diagnostics are ignored. It means they become editorial evidence instead of unconditional vetoes.

The final publication contract should distinguish:

- **Clean source-faithful module:** Source fidelity passes and publication gates pass.
- **Reconciled playable module:** Source fidelity has blockers/degradation, but LLM Builder reviewed and reconciled them, and publication gates pass.
- **Blocked module:** LLM Builder reconciliation fails or deterministic runtime/publication gates fail.

## Current Failure Point

Current final build flow in `web/extensions/toolkit_homebrew_packet_builder.py`:

```text
ModuleBuilder succeeds
  -> build_build_fidelity_report(...)
  -> can_continue_after_build_fidelity(...)
  -> if false: build_result.status = "blocked"
  -> readiness/finisher never runs
```

Current issue:

- `can_continue_after_build_fidelity()` treats source-fidelity blockers as terminal build blockers.
- This prevents final editor judgment.
- It stops readiness/finisher even when the module directory exists and may validate.

## Target Final Flow

```text
ModuleBuilder succeeds
  -> build_build_fidelity_report(...)
  -> classify final blockers
       structural fatal?
         yes -> block immediately
       editorial/source-fidelity blocker?
         yes -> run final LLM Builder reconciliation
       no blockers?
         continue
  -> persist reconciliation report
  -> rerun final reports
  -> readiness gate
  -> finisher/publication gate
  -> GUI status shows playable pass/degraded/blocked accurately
```

## Fatal vs Editorial Blockers

Final blockers must be classified before deciding whether to stop.

### Fatal Blockers

These should remain fail-closed before or after reconciliation:

- Module directory missing.
- Invalid JSON.
- Schema validation failure after repair budget.
- Missing canonical module artifacts required for play.
- Broken area/map/plot topology that cannot be reconciled.
- Party tracker/schema defaults invalid after normalization.
- Unresolved runtime-critical monster/NPC/media artifacts when required by publishability.
- Finisher failure.
- Report disagreement that cannot be explained by accepted reconciliation metadata.
- LLM provider failure during a required final reconciliation pass.

### Editorial Blockers

These should trigger final LLM Builder reconciliation, not immediate build failure:

- Source atom classified as a required location but likely a section heading, table label, mechanic, trap component, or prose fragment.
- Source NPC/location missing from generated module but not necessary for a playable module after Builder judgment.
- Blueprint/source-lock mismatch that can be folded into an existing room, NPC, plot point, or DM instruction.
- Non-verifiable puzzle/clue/encounter/item source atoms that can be preserved as prose rather than exact JSON entities.
- Source fidelity blockers caused by extractor overreach rather than actual adventure omissions.

## Final Reconciliation Authority

LLM Builder at the final stage may:

- Reclassify a required source atom as a mechanic, trap, clue, hazard, flavor note, or advisory item.
- Remove a bogus atom from required-location/NPC expectations for this build.
- Merge a source atom into an existing generated location, NPC, plot point, or DM instruction.
- Create or modify module JSON where a real missing element is needed for playability.
- Rewrite generated structure to make the module coherent and playable.
- Mark a source-fidelity blocker as editorially accepted when literal preservation is not appropriate.

LLM Builder must not:

- Emit invalid JSON.
- Edit runtime-only files as the final canonical output.
- Hide source-fidelity degradation by falsely reporting a clean source-fidelity pass.
- Bypass schema/readiness/publishability validation.
- Treat `MODULE_SUMMARY.md` as source truth.

## Required Artifacts

Add workspace-local final reconciliation artifacts:

### `final_reconciliation_brief.json`

Builder-facing evidence package.

Suggested fields:

```json
{
  "version": "accurate_ingest_final_reconciliation_brief.v1",
  "job_id": "...",
  "module_name": "Well_of_Ruin",
  "module_dir": "modules/Well_of_Ruin",
  "trigger": "build_fidelity_blocked",
  "blockers": [],
  "warnings": [],
  "source_excerpts": [],
  "generated_module_summary": {},
  "editable_surfaces": [
    "module_context.json",
    "module_context_BU.json",
    "module_plot.json",
    "module_plot_BU.json",
    "areas/*_BU.json",
    "map_*.json"
  ],
  "instructions": {
    "goal": "Produce a playable, schema-valid NEQ module",
    "source_fidelity_role": "diagnostic evidence, not absolute veto",
    "must_validate": true
  }
}
```

### `final_reconciliation_patch.json`

LLM Builder output patch plan.

Suggested fields:

```json
{
  "version": "accurate_ingest_final_reconciliation_patch.v1",
  "status": "ready|refused|failed",
  "decisions": [
    {
      "blocker": "Required location 'Trigger' not found in module",
      "decision": "reclassify",
      "from": "required_location",
      "to": "mechanic_heading",
      "reason": "Heading describes trap trigger rules, not a place",
      "target_surface": "module_plot_BU.json",
      "action": "preserve_as_dm_guidance"
    }
  ],
  "file_patches": [],
  "source_fidelity_claim": "reconciled_degraded",
  "publication_intent": "playable_module"
}
```

### `final_reconciliation_report.json`

Post-application audit report.

Suggested fields:

```json
{
  "version": "accurate_ingest_final_reconciliation_report.v1",
  "status": "pass|degraded|blocked|failed",
  "reconciliation_status": "accepted|not_required|failed",
  "source_fidelity_effective_status": "pass|reconciled_degraded|blocked",
  "playable_publication_candidate": true,
  "decisions": [],
  "validation_after_reconciliation": {},
  "publishability_after_reconciliation": {},
  "report_agreement_after_reconciliation": {},
  "notes": []
}
```

## Publication Status Semantics

Add clear status language:

| Status | Meaning |
|---|---|
| `source_fidelity_status: pass` | Source fidelity passed cleanly. |
| `source_fidelity_status: blocked` | Source fidelity has unresolved blockers. |
| `source_fidelity_effective_status: reconciled_degraded` | Source fidelity blockers were reviewed and accepted/reconciled by LLM Builder. |
| `playable_publication_status: pass` | Final module is valid and publishable for play. |
| `playable_publication_status: blocked` | Final module is not publishable. |

The GUI should be allowed to show:

```text
Playable publication: PASS
Source fidelity: RECONCILED/DEGRADED
```

It should not show:

```text
Source fidelity: PASS
```

unless source fidelity truly passed.

## Proposed OpenSpec Plan

This should likely be a small chain of two changes, not one giant change.

### Change 1: `toolkit-accurate-ingest-final-reconciliation-boundary`

Purpose:

Define and implement the final pipeline boundary so build-fidelity source blockers trigger reconciliation instead of stopping the build immediately.

Capabilities:

- `accurate-ingest-final-blocker-classification`
- `accurate-ingest-final-reconciliation-brief`
- `accurate-ingest-build-fidelity-nonterminal-editorial-blockers`
- `accurate-ingest-reconciled-source-fidelity-status`
- `toolkit-homebrew-final-status-ux`

Step-by-step builder tasks:

1. Baseline `Well_of_Ruin` failure.
   - Reproduce or load existing workspace artifacts.
   - Confirm module directory exists.
   - Confirm blocker terms are source headings/mechanics, not locations.
   - Record baseline in tasks notes.

2. Add final blocker classifier.
   - New helper, likely `utils/toolkit_final_blocker_classifier.py`.
   - Input: `build_fidelity_report.json`, module directory, source graph, builder blueprint report.
   - Output: fatal blockers, editorial blockers, warnings.
   - Classify source-location/NPC/puzzle fidelity mismatches as editorial unless tied to invalid JSON/schema/topology.
   - Keep module-missing/report-load failures fatal.

3. Add final reconciliation brief builder.
   - New helper, likely `utils/toolkit_final_reconciliation.py`.
   - Build `final_reconciliation_brief.json` from build-fidelity blockers, source refs/excerpts, generated module summary, and editable target surfaces.
   - Persist it in the workspace.
   - Keep this step deterministic and provider-free.

4. Change packet builder final gate behavior.
   - In `web/extensions/toolkit_homebrew_packet_builder.py`, replace direct `status=blocked` for all `can_continue=False` with classifier logic.
   - Fatal blockers still block.
   - Editorial blockers set build result metadata such as `final_reconciliation_required: true` and continue to reconciliation.
   - Persist build-fidelity and source-fidelity rollups unchanged as evidence.

5. Add placeholder/non-provider reconciliation acceptance path for tests.
   - For Change 1, do not require full LLM patching yet.
   - Add report/status plumbing proving an accepted reconciliation can let readiness/finisher run.
   - Tests can use injected/mock reconciliation decisions.

6. Update report agreement semantics.
   - Modify `utils/toolkit_report_agreement.py` so `source_fidelity_status != pass` does not automatically block playable publication if `final_reconciliation_report.status in {pass, degraded}` and `source_fidelity_effective_status == reconciled_degraded`.
   - Preserve hard blocking when no accepted reconciliation exists.

7. Update GUI status language.
   - Show `Playable publication: pass` separately from `Source fidelity: reconciled/degraded`.
   - Avoid implying clean source fidelity.
   - Avoid support-link failure language when the final module is valid.

8. Tests.
   - Add provider-free tests for Well-like bogus heading blockers.
   - Add tests that fatal blockers still block.
   - Add report-agreement tests for reconciled source fidelity.
   - Add GUI template/source-contract tests for status wording.

9. Verification.
   - `.venv/bin/python -m py_compile` for touched files.
   - Targeted tests.
   - `openspec validate toolkit-accurate-ingest-final-reconciliation-boundary`.

Acceptance:

- Build-fidelity source blockers no longer stop a generated module before reconciliation.
- Fatal structural failures still stop the build.
- Final status can distinguish playable publication from clean source fidelity.
- No front/middle pipeline behavior changes.

### Change 2: `toolkit-accurate-ingest-llm-builder-final-editor`

Purpose:

Implement the LLM Builder final editorial reconciliation pass that consumes the reconciliation brief and edits/reclassifies/cleans final module structures before validation and publication.

Capabilities:

- `accurate-ingest-llm-builder-final-editorial-pass`
- `accurate-ingest-final-reconciliation-patch-contract`
- `accurate-ingest-final-json-validation-loop`
- `accurate-ingest-bogus-source-atom-cleanup`
- `accurate-ingest-final-reconciliation-reporting`

Step-by-step builder tasks:

1. Design the final editor prompt contract.
   - New prompt file, likely `prompts/toolkit/final_reconciliation_builder_prompt.txt`.
   - Inputs: blocker evidence, source excerpts, generated module summary, editable surfaces, validation goals.
   - Output: strict JSON patch plan, not freeform prose.
   - Explicitly allow reclassify/delete/merge/downgrade decisions for bogus blockers.
   - Explicitly require schema-valid playable module as the goal.

2. Add LLM final editor runner.
   - New helper, likely `utils/toolkit_llm_final_reconciliation.py`.
   - Use existing chat client/model routing patterns.
   - Fail closed on provider failure if reconciliation is required.
   - Support injected/mock provider output for tests.

3. Define patch contract.
   - Accept only whitelisted file targets and operations.
   - Prefer whole-file JSON object replacement or path-scoped JSON patches where safe.
   - Reject edits to runtime-only files unless they are mirrored from canonical outputs by existing tooling.
   - Reject invalid patch shapes.

4. Apply final patch safely.
   - Use atomic writes.
   - Validate JSON after each changed file.
   - Preserve BU/live parity rules.
   - Keep backups in workspace or module backup location as current rebuild policy requires.

5. Add post-reconciliation validation loop.
   - Run schema validation.
   - Run readiness/publishability/report agreement.
   - If validation fails with repairable issues, allow one bounded retry back to LLM Builder with validation errors.
   - Do not allow infinite retries.

6. Persist final reconciliation report.
   - Include decisions, changed files, validation outcome, publishability outcome, and source-fidelity effective status.
   - Copy or summarize relevant status into module-level reports where appropriate.

7. Well of Ruin regression.
   - Use existing `Well of Ruin.md` fixture or workspace artifact.
   - Assert `Trigger`, `Passive Element`, and `Active Element` are not required locations after reconciliation.
   - Assert their meaning is either dropped as bogus structure or preserved as mechanics/DM guidance.
   - Assert final module validates and reaches publishable/playable status if other gates pass.

8. Safety tests.
   - LLM tries invalid JSON -> fail closed.
   - LLM tries to edit forbidden file -> fail closed.
   - LLM tries to mark source fidelity pass without actual pass -> fail closed or normalize to reconciled_degraded.
   - LLM provider unavailable -> fail closed with clear diagnostic.
   - Structural fatal blocker remains fatal.

9. Verification.
   - Targeted unit tests.
   - Accurate-ingest GUI/unified-flow tests.
   - Build-fidelity/report-agreement tests.
   - `openspec validate toolkit-accurate-ingest-llm-builder-final-editor`.

Acceptance:

- LLM Builder can act as final editor for stubborn source-fidelity blockers.
- Bogus source atoms do not infect final module structure or Narrator context.
- Final module publication depends on JSON/schema/playability, not literal source-fidelity veto.
- Source-fidelity degradation remains visible and honest.

### Optional Change 3: `toolkit-accurate-ingest-source-atom-classification-cleanup`

Purpose:

Reduce the number of bogus final blockers by improving deterministic source atom classification.

This is useful but should not be required before final reconciliation exists.

Capabilities:

- `accurate-ingest-heading-role-classification`
- `accurate-ingest-mechanic-heading-detection`
- `accurate-ingest-location-candidate-precision`

Step-by-step builder tasks:

1. Add heading role classification.
   - Distinguish place headings from mechanics, tables, triggers, elements, rules, labels, and subsections.

2. Add a non-location stoplist and pattern rules.
   - Examples: `Trigger`, `Passive Element`, `Active Element`, `Effects`, `Rewards`, `Scaling`, `Tactics`, `Complications`.
   - Avoid overfitting by classifying as `mechanic_heading` or `section_heading`, not deleting all instances blindly.

3. Update source graph atom criticality.
   - Mechanic headings should not become required locations.
   - They may become mechanics/advisory source atoms.

4. Tests.
   - Well of Ruin headings are not locations.
   - Real numbered/map-key locations remain locations.
   - Numillian preservation remains stable.

Acceptance:

- Fewer bogus fidelity blockers reach final reconciliation.
- Final reconciliation remains the safety net when extractor classification is still wrong.

## Suggested Builder Execution Order

Recommended order:

1. Implement Change 1 first.
   - It creates the final boundary and status semantics.
   - It can be provider-free and test-heavy.

2. Implement Change 2 second.
   - It adds live LLM Builder final editorial control.
   - It relies on Change 1 artifacts and status plumbing.

3. Implement Change 3 later if needed.
   - It improves extraction quality but is not the product-critical fix.

## Testing Strategy

### Required Fixtures

- `Well of Ruin.md`: bogus heading-as-location blockers.
- Numillian: regression for previous source-fidelity preservation and playable-publication closure.
- A small synthetic module with real missing location blocker to prove fatal/editorial distinction.

### Required Test Classes

- Build-fidelity classifier tests.
- Reconciliation brief shape tests.
- Report-agreement reconciled-source-fidelity tests.
- Packet builder flow tests proving editorial blockers continue.
- LLM final editor patch validation tests.
- GUI status wording/source-contract tests.

### Required Commands

Use `.venv/bin/python` for all Python verification.

Suggested final verification after implementation:

```bash
.venv/bin/python -m py_compile utils/toolkit_final_blocker_classifier.py utils/toolkit_final_reconciliation.py utils/toolkit_llm_final_reconciliation.py web/extensions/toolkit_homebrew_packet_builder.py utils/toolkit_report_agreement.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_module_build_publication_parity scripts.test_builder_blueprint_fidelity_gate
.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin
.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json
openspec validate toolkit-accurate-ingest-final-reconciliation-boundary
openspec validate toolkit-accurate-ingest-llm-builder-final-editor
```

## Open Questions For Review

1. Should LLM Builder final reconciliation be required whenever build fidelity is blocked, or only when the classifier says blockers are editorial?

Recommended: only editorial blockers invoke LLM final reconciliation. Fatal structural blockers remain fail-closed.

2. Should reconciled modules be listed in the public catalog automatically?

Recommended: yes, if validation/readiness/publishability/report agreement pass. The module should carry source-fidelity effective status as `reconciled_degraded`.

3. Should final reconciliation be allowed to reduce source fidelity below the original generated module if it improves playability?

Recommended: yes. At final publication, playability and valid module structure take precedence. The source-fidelity report must remain honest.

4. Should bogus source atoms be removed from the workspace source graph or only suppressed in final publication metadata?

Recommended: do not mutate original source graph artifacts. Persist final reconciliation decisions separately and prevent bogus atoms from infecting final module structures and final status.

## Success Definition

The final accurate-ingest product succeeds when a facilitator can upload a readable adventure markdown/PDF/source text and receive a playable, schema-valid NEQ module, even if final source-fidelity diagnostics require editorial reconciliation.

The system should honestly report:

```text
Playable: yes
Source fidelity: reconciled/degraded
Final editor: LLM Builder
Validation: pass
Publishability: pass
```

That is preferable to:

```text
Build failed because markdown heading 'Trigger' was not generated as a room.
```
