# LLM Adaptation Builder Plan

Status: Draft for review
Date: 2026-08-03
Decision gate: Do not create the OpenSpec scaffolds or modify the current accurate-ingest worktree until this plan is approved.

## Executive Decision

The default Homebrew upload workflow will become an LLM-led adaptation workflow.

The source adventure will be treated as material to interpret and adapt into a fresh NEQ-TTRPG module. Literal source-fidelity preservation will no longer be the default publication objective.

The existing ModuleBuilder will remain the creative module construction engine. It will receive a bounded adaptation dossier rather than a source-locked atom roster.

Python will remain authoritative for:

- Module file layout and identifiers.
- Schema and structural validation.
- Mechanical repair and reference closure.
- Semantic authority derived from the generated module.
- Report persistence and freshness.
- MODULE_SUMMARY.md generation and download readiness.
- World registry and campaign registration.

The LLM will remain authoritative for:

- Source interpretation.
- Adaptation choices.
- Plot, prose, NPC, encounter, item, and hook design.
- NEQ-specific connective tissue.
- Final semantic revision decisions after a failed build.

## Current Failure: JeremysMagicShop

The current failure is primarily an API request-shape regression, not evidence that the source cannot be processed.

- `gpt-5.6-luna` rejected direct `temperature=0.7` with HTTP 400.
- The GPT-5 chat-parameter shim exists but is not applied to the Homebrew normalizer and several ModuleBuilder generator paths.
- All 181 section extraction units degraded before useful semantic processing completed.
- The source graph still produced 515 atoms, including 178 location candidates.
- The catalogue format caused item headings to be promoted as locations.
- The placeholder normalized packet was persisted, but no module reached ModuleBuilder, finishing, Markdown generation, or registry integration.
- The GUI surfaced a generic normalizing failure instead of offering an adaptation path.

The immediate conclusion is that another source-atom triage layer is not the product solution. The source is an item catalogue and should be adapted into a playable shop or location module rather than forced through a room-oriented fidelity contract.

## Goals

- Make LLM adaptation the default for readable Homebrew uploads.
- Preserve accurate-ingest as an explicit legacy and diagnostic mode.
- Let the LLM create a coherent NEQ-TTRPG module from source material.
- Allow intentional omission, reinterpretation, and original NEQ connective material.
- Use the developing world narrative seed as bounded optional context.
- Run one bounded LLM semantic adaptation revision when a module build fails for content or semantic reasons.
- Guarantee that every module reported as complete passes the publication contract.
- Guarantee that failed attempts do not leave a registered or partially published module.
- Produce a readable and downloadable `MODULE_SUMMARY.md` for every completed module.
- Verify that every completed module is registered in the world registry and visible to the active campaign when one exists.
- Preserve source rights and adaptation provenance in generated artifacts.

## Non-Goals

- Perfect textual or atom-level source reproduction.
- Building another deterministic source-fidelity classifier.
- Letting the LLM write arbitrary live JSON files.
- Letting the LLM mutate `world_registry.json`, `campaign.json`, or mechanical runtime state.
- Unbounded provider retries or automatic regeneration loops.
- Treating an LLM response as proof that a module is valid.
- Hiding source omission or adaptation behind a false source-fidelity pass.
- Replacing existing Python schema, readiness, or publication gates.

## Target Lifecycle

```text
Uploaded source
    |
    v
Source intake, rights metadata, and bounded source context
    |
    v
LLM adaptation author -> adaptation_dossier.json
    |
    v
ModuleBuilder adaptation build in an isolated staging workspace
    |
    v
Python structural validation and mechanical closure
    |
    v
Readiness, semantic authority, semantic probes, and report agreement
    |
    +--> infrastructure failure -> explicit infrastructure failure
    |
    +--> content or semantic failure -> LLM final adaptation audit
                                      |
                                      v
                              revised adaptation dossier
                                      |
                                      v
                              fresh staged rebuild
    |
    v
MODULE_SUMMARY.md quality gate
    |
    v
Registry integration and verification
    |
    v
Campaign availability synchronization and verification
    |
    v
Completed adaptation
```

## Success Guarantee

The system cannot guarantee that an arbitrary provider call succeeds on the first attempt.

It can guarantee the following contract:

- `completed` is emitted only after every required gate passes.
- A provider failure is never presented as a semantic success.
- A failed semantic revision does not register the module.
- Registry integration occurs only after validation, report agreement, and Markdown checks pass.
- A post-registration failure triggers rollback or an explicit failed publication state.
- A module that cannot pass within the bounded revision budget remains failed and retryable.

## Adaptation Dossier Contract

The adaptation author will return strict JSON with a versioned contract. The dossier is the creative handoff to ModuleBuilder and is not itself accepted as a playable module.

Required dossier concepts:

- `version`.
- `status`.
- `adaptation_mode`.
- `source_title`.
- `adapted_title`.
- `source_hash`.
- `source_profile` such as `adventure`, `catalogue`, `location`, `lore`, `encounter`, or `sandbox`.
- `module_tone`.
- `level_range`.
- `starting_location`.
- `areas`.
- `plot_objective`.
- `plot_progression`.
- `npc_seeds`.
- `encounter_seeds`.
- `item_seeds`.
- `puzzle_or_trial_seeds` when appropriate.
- `retained_source_elements`.
- `omitted_source_elements`.
- `original_adaptation_elements`.
- `world_narrative_hooks`.
- `continuity_hints`.
- `rights_class`.
- `adaptation_notice`.
- `assumptions`.
- `warnings`.

The prompt must require:

- JSON only.
- No copied source prose.
- Source-faithful intent where useful, without a literal-fidelity claim.
- Explicit labeling of invented NEQ connective material.
- Generic fantasy and SRD 5.2.1-compatible mechanics.
- ASCII-safe output for persisted contracts and console-facing content.
- Refusal when source rights or input material are insufficient for adaptation.

## Source Profiles

The adaptation author must classify the source by playable intent rather than forcing every source into a room map.

### Adventure

Preserve the central premise and major beats while rebuilding locations, encounters, and progression for NEQ.

### Catalogue or Shop

Create one or more shop locations, item tables, merchant context, optional complications, and playable hooks. Item headings must not become locations by default.

### Location or Dungeon

Use the source location as inspiration for one coherent area graph and add only the necessary playable structure.

### Lore or Setting Material

Convert the material into a location, faction, rumor, quest hook, or module seed with an optional playable entry point.

### Encounter or Scenario

Build a compact encounter module with setup, stakes, resolution paths, and appropriate stat references.

### Sandbox

Create an open-ended location or regional module with multiple hooks and no invented mandatory linear plot unless the source supports one.

## ModuleBuilder Boundary

ModuleBuilder is the creative worker, not the source-fidelity authority and not the publication authority.

ModuleBuilder MUST:

- Receive `build_mode: "llm_adaptation"`.
- Receive the adaptation dossier and bounded world context.
- Generate a fresh module tree from the adapted concept.
- Preserve NEQ structural contracts while writing rich narrative content.
- Write only into the isolated build target.

ModuleBuilder MUST NOT:

- Treat every source candidate as a required entity.
- Claim source-fidelity completion.
- Write to `world_registry.json` or `campaign.json`.
- Bypass schema or readiness validation.
- Mutate an already registered module without an explicit overwrite authorization.

## Final LLM Semantic Adaptation Revision

The final revision is a new adaptation contract, not an extension of the existing `accurate_ingest_final_reconciliation_patch.v1` patch contract.

When a staged module fails semantic or content validation, Python will persist an `adaptation_failure_report.json` containing:

- Build attempt identity.
- Adaptation dossier identity.
- Failure class.
- Exact validator and audit findings.
- Compact module summary.
- Current areas, locations, NPCs, monsters, and plot beats.
- Required publication outcomes.
- World context version and hash.

The LLM semantic auditor will return:

- `revise`, `refuse`, or `failed`.
- A revised adaptation dossier or a complete rebuild directive.
- Explicit retained, omitted, and newly adapted elements.
- A reason for each revision.
- A source-fidelity disclaimer.

Python will validate the response contract, then run a fresh ModuleBuilder build. The LLM will never patch arbitrary live files.

The default revision budget is one final semantic revision. A configurable maximum of two may be supported. Infrastructure failures do not consume semantic revision budget.

## Failure Classification

### Infrastructure Failure

Provider outage, unsupported request parameters, quota, timeout, missing dependency, file I/O, or malformed runtime environment.

Outcome: no semantic revision. Persist an explicit infrastructure failure and leave no registry side effect.

### Mechanical Structural Failure

Invalid JSON, missing required files, unresolved monster reference, invalid schema field, or broken structural topology.

Outcome: bounded Python mechanical repair where safe. If content is required, pass the failure to the LLM adaptation revision.

### Semantic Adaptation Failure

Unresolved player-facing destination, incoherent plot path, missing playable location, contradictory NPC authority, or unusable encounter intent.

Outcome: final LLM adaptation audit followed by a fresh rebuild.

### Rights or Policy Failure

Missing rights classification, prohibited content, or refusal from the adaptation author.

Outcome: blocked with operator-facing remediation. No registration.

### Publication Failure

Missing readable Markdown, stale reports, registry verification failure, or campaign visibility failure.

Outcome: rollback or failed publication. Never report `completed`.

## World Narrative Seed Integration

The world narrative seed is optional context and never a direct mutation surface.

The bounded context pack may include:

- Current `campaign_world_model`.
- Active high-priority narrative threads.
- Actor-state pressures.
- Existing module registry context.
- Approved `module_narrative_seeds`.
- Seed database version and hash.

The adaptation author may propose:

- Module hooks into existing threads.
- New candidate continuations.
- Faction or actor pressure links.
- Follow-up module seeds.

Python will persist proposals as adaptation provenance. It will not write campaign canon directly from the LLM response.

If the world narrative seed is unavailable, adaptation continues with a bounded generic NEQ context and records `world_seed_status: unavailable`.

## Publication Transaction

Adaptation publication MUST use a staging or backup-safe output path.

Required order:

1. Generate adaptation dossier.
2. Build module in staging.
3. Run schema validation.
4. Run deterministic mechanical closure.
5. Run readiness audit.
6. Derive semantic authority from the generated module.
7. Run semantic audit and probes.
8. Persist fresh validation, readiness, adaptation, and build reports.
9. Run report agreement and freshness checks.
10. Render `MODULE_SUMMARY.md`.
11. Run Markdown quality checks.
12. Integrate into `world_registry.json`.
13. Verify registry presence.
14. Synchronize and verify active campaign availability when a campaign exists.
15. Promote the staged result to completed status.

Registry integration MUST occur after Markdown and report checks. The current finisher ordering that registers before Markdown generation is insufficient for the adaptation guarantee and must be corrected for this mode.

## Adaptation Publication Status

The report model must separate adaptation from source fidelity.

Required fields:

- `build_mode: "llm_adaptation"`.
- `adaptation_status: "initial|revised|failed"`.
- `source_fidelity_status: "not_applicable"` in adaptation mode.
- `source_fidelity_claim: "adapted_not_literal"`.
- `playable_publication_status`.
- `effective_publishable_status`.
- `final_adaptation_revision_used`.
- `world_seed_context_hash`.
- `adaptation_notice`.

Legacy source-fidelity reports remain available as provenance diagnostics but MUST NOT block an adaptation solely because it differs from the source.

## Markdown Download Contract

Every completed adaptation MUST have a persisted `MODULE_SUMMARY.md` that:

- Is valid UTF-8.
- Contains the adapted module title.
- Contains readable section headings.
- Contains at least one playable area or location.
- Contains the adapted plot or module premise.
- Contains the adaptation notice.
- Exceeds the minimum download size.
- Contains no raw JSON dump, traceback, or provider error.

The download endpoint MUST serve the persisted file and MUST NOT regenerate a completed module on every request.

## Copyright and Provenance

Generated module credits will include:

```text
Adapted for NEQ-TTRPG
```

The module will also retain:

- Original source title.
- Source hash.
- Upload rights classification.
- Adaptation timestamp.
- Adaptation model metadata.
- World seed version and hash when used.

The pipeline records provenance and operator-provided rights classification. It does not make an independent legal determination about source ownership.

## GPT-5.6 Luna Compatibility Prerequisite

Before adaptation work is enabled, all build-time LLM calls MUST use the shared chat-parameter helper.

Priority scope:

- `utils/toolkit_homebrew_normalizer.py`.
- `core/generators/module_builder.py`.
- `core/generators/module_generator.py`.
- `core/generators/area_generator.py`.
- `core/generators/location_generator.py`.
- `core/generators/location_summarizer.py`.
- `core/generators/plot_generator.py`.
- `core/generators/npc_builder.py`.
- `core/generators/monster_builder.py`.
- `utils/homebrewery_adventure_writer.py`.
- Toolkit classification and spatial calls.

Acceptance requirements:

- GPT-5-family calls omit unsupported `temperature` and `top_p`.
- GPT-5-family calls include the correct reasoning and verbosity profile.
- OpenRouter keeps its existing request shape.
- Normalizer and ModuleBuilder tests capture the final request kwargs.
- No direct GPT-5 build path can reproduce the JeremysMagicShop 400 error.

## OpenSpec Scaffold Plan

The work requires two scaffolds.

### Scaffold 1: toolkit-gpt5-build-path-compatibility

Purpose: repair the provider contract independently of adaptation behavior.

Expected artifacts:

- `proposal.md`.
- `design.md`.
- `tasks.md`.
- `README.md`.
- `.openspec.yaml`.
- Delta spec `gpt5-builder-chat-params-contract`.
- Delta spec `toolkit-homebrew-provider-compatibility`.

Expected task groups:

1. Inventory and classify all build-time provider call sites.
2. Route normalizer calls through `get_chat_completion_params`.
3. Route ModuleBuilder and generator calls through the helper.
4. Route Markdown writer and toolkit auxiliary calls through the helper.
5. Remove direct `top_p` from GPT-5 runtime paths.
6. Add provider-free request-shape tests.
7. Run focused regressions and a bounded live Luna smoke.

### Scaffold 2: toolkit-llm-adaptation-builder

Purpose: implement the complete LLM adaptation and publication lifecycle.

Expected artifacts:

- `proposal.md`.
- `design.md`.
- `tasks.md`.
- `README.md`.
- `.openspec.yaml`.
- `executor_prompts.md`.
- Delta spec `toolkit-llm-adaptation-authoring`.
- Delta spec `toolkit-adaptation-final-revision`.
- Delta spec `toolkit-adaptation-publication-transaction`.
- Delta spec `toolkit-adaptation-markdown-download`.
- Delta spec `toolkit-adaptation-provenance`.
- Delta spec `toolkit-adaptation-world-narrative-seed`.

Expected task groups:

1. Define versioned adaptation dossier and report contracts.
2. Add adaptation author prompt and provider runner.
3. Add source profile handling for catalogue and non-room sources.
4. Route default Homebrew jobs to adaptation mode.
5. Add ModuleBuilder adaptation handoff.
6. Add isolated staging and fresh rebuild behavior.
7. Add failure packet and final LLM semantic revision.
8. Add adaptation-aware report agreement and source-fidelity handling.
9. Add publication ordering and registry-last transaction behavior.
10. Add Markdown quality gate and download verification.
11. Add world narrative context retrieval and provenance.
12. Add adaptation copyright and rights metadata.
13. Add GUI progress, failure, and retry status handling.
14. Add provider-free contract and integration tests.
15. Run JeremysMagicShop end-to-end verification.

No separate scaffold is recommended for the final semantic audit. It is part of the adaptation lifecycle and must be tested with the publication transaction.

No separate world-narrative scaffold is recommended until the seed database and retrieval contract are independently ready. The adaptation change should initially use a feature-gated provider with an unavailable-seed fallback.

## Accurate-Ingest Transition

The following plans become historical references after the existing changes are checkpointed and reviewed:

- `plans/accurate-ingest.md`.
- `plans/accurate-ingest-fix.md`.
- `plans/accurate_ingest_final_reconciliation.md`.
- `plans/accurate-ingest-numillian-release-proof-diagnostics.md`.

Retain as reusable infrastructure:

- Schema validation.
- Readiness and publishability gates.
- Mechanical monster, spatial, calendar, and media closure.
- Report agreement and freshness checks.
- Semantic authority generation from generated module data.
- Atomic writes and path safety.
- MODULE_SUMMARY.md rendering.
- Registry verification and campaign visibility checks.
- Safe parser and provider plumbing from the existing final reconciliation runner.

Retire as default authoring or publication requirements:

- Mandatory source-fidelity coverage.
- Required preservation of every extracted atom.
- Repeated deterministic entity triage layers.
- Source-locked ModuleBuilder prompts.
- Final reconciliation as a narrow source-cleanup patch.

## Current Worktree Handling

The repository currently contains uncommitted accurate-ingest production changes and four untracked active OpenSpec change directories:

- `toolkit-accurate-ingest-llm-builder-final-editor`.
- `toolkit-accurate-ingest-modulebuilder-structural-repair`.
- `toolkit-accurate-ingest-publication-readiness-closure`.
- `toolkit-accurate-ingest-source-atom-triage-hardening`.

These changes MUST NOT be reverted or deleted.

Before creating the new adaptation scaffolds:

1. Capture the current worktree state.
2. Review each active change for reusable safety code.
3. Identify which production edits are intended to remain as mechanical infrastructure.
4. Mark the literal-fidelity portions as superseded or legacy only after review.
5. Keep the current changes separate from the new adaptation change history.

No destructive cleanup, archive, reset, or forced staging is part of this plan.

## Verification Matrix

Provider-free tests MUST cover:

- Adaptation prompt contract.
- Dossier parsing and required fields.
- Source profile classification.
- Rights and provenance handling.
- World seed unavailable fallback.
- ModuleBuilder adaptation handoff.
- Failure packet construction.
- Final LLM revision response parsing.
- Fresh rebuild and staging isolation.
- No registry side effect on failed builds.
- Adaptation-aware report agreement.
- Markdown quality gate.
- Registry and campaign verification.
- Existing accurate-ingest regression compatibility.
- GPT-5.6 Luna request parameters.
- ASCII compliance.

JeremysMagicShop acceptance scenario MUST verify:

- The Luna temperature error is gone.
- The source does not fail merely because it lacks room structure.
- A shop or catalogue adaptation is generated.
- The module validates.
- The Markdown download is readable.
- `Adapted for NEQ-TTRPG` is present.
- The module is in `world_registry.json`.
- The active campaign can discover it.

Failure injection MUST verify:

- A semantic failure invokes the final LLM revision.
- The revised build starts from a fresh staging target.
- A failed final revision leaves no completed module or registry entry.
- Provider failures are reported as infrastructure failures.

## Rollout and Rollback

Rollout:

1. Land GPT-5 build-path compatibility.
2. Run provider-free adaptation tests.
3. Run one bounded JeremysMagicShop live smoke.
4. Enable adaptation mode behind a feature flag.
5. Compare adaptation output against existing module publication gates.
6. Make adaptation the default after the smoke is stable.

Rollback:

- Restore the legacy accurate-ingest mode flag.
- Disable adaptation authoring without removing its artifacts.
- Preserve staged failed outputs for diagnostics.
- Do not remove existing registered modules.
- Do not rewrite source uploads.
- Restore registry state from the pre-publication backup if a transaction fails.

## Review Decisions Required

The implementation should not begin until these decisions are confirmed:

- Whether the final semantic revision budget is one or two attempts.
- Whether adaptation may invent new named NPCs and factions by default, or only original hooks and connective prose.
- Whether `Adapted for NEQ-TTRPG` is the exact required notice in all generated Markdown and module metadata.
- Whether campaign availability must be updated immediately or only on the next startup scan.
- Whether the existing uncommitted accurate-ingest changes should be checkpointed as one legacy baseline or split into reusable infrastructure and historical fidelity work.
