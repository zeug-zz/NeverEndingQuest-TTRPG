## Context

`toolkit-accurate-ingest-modulebuilder-structural-repair` adds deterministic monster closure, spatial repair, calendar normalization, and fatal structural blocker routing. It does not address source atom typing. The active final-editor change then expects structural validation to pass before step 7.3 can prove final-editor behavior.

The latest Well of Ruin failure class is different: source extraction and triage promote trap/table data into `npc` atoms. Build fidelity then treats those blueprint NPC roster entries as required NPCs and reports missing NPC blockers. A final editor with empty `source_excerpts` cannot reliably distinguish bogus table effects from real missing NPCs.

## Goals / Non-Goals

**Goals:**

Contract Layer (MUST):

- Prevent table effect labels and effect prose from entering required NPC coverage.
- Preserve legitimate table-sourced NPC names.
- Preserve structural repair routing and final-editor safety gates.
- Enrich final reconciliation briefs with compact source refs/excerpts and generated-module summary when artifacts are available.
- Add provider-free tests that reproduce the Well NPC false-positive blocker class.

Guidance Layer (SHOULD):

- Keep code changes narrow and helper-oriented.
- Prefer deterministic checks based on table headers, sentence shape, and section context.
- Preserve source evidence in non-actor categories where feasible.

**Non-Goals:**

- Do not broaden the final editor into a general source extraction repair agent.
- Do not modify structural repair helpers unless tests prove a direct integration issue.
- Do not rewrite source graph, normalized packet, blueprint, backstage audit, or uploaded source artifacts after the fact.
- Do not weaken full-module validation, publishability, or report-agreement gates.

## Decisions

### Decision 1: Filter table-cell NPC extraction by table role

Contract Layer (MUST): table cells SHALL become NPC/entity candidates only when table headers or nearby context indicate identity-bearing rows. Tables with headers such as `Effect`, `Complication`, `Result`, `Trigger`, `Passive Element`, `Active Element`, `Spell`, or `Description` SHALL NOT promote those cells to required NPC candidates.

Guidance Layer (SHOULD): implement small helpers in `utils/toolkit_source_manifest.py`, for example `_table_headers_indicate_entity_identity(...)` and `_table_headers_indicate_effect_text(...)`, then use them in `_extract_entity_candidates(...)` before `_register(...)`.

### Decision 2: Add deterministic non-actor prefiltering in triage

Contract Layer (MUST): obvious non-actor candidates SHALL be rejected or classified as non-actor before blueprint NPC roster construction. This includes full sentences, long clauses, table effect prose, and one-word capitalized mechanic/effect verbs in trap/effect sections.

Guidance Layer (SHOULD): extend `build_prefilter_decision(...)` in `utils/toolkit_entity_candidate_triage.py` rather than adding a provider-backed call.

### Decision 3: Keep blueprint NPC roster dependent on triage

Contract Layer (MUST): `utils/toolkit_builder_blueprint.py` SHALL NOT include rejected or non-actor triage decisions in `npc_roster`, and no required NPC build-fidelity blocker SHALL be emitted from those excluded candidates.

Guidance Layer (SHOULD): the existing `_is_triage_blocked_for_npc_roster(...)` path may already satisfy much of this if prefilter decisions are correctly written.

### Decision 4: Improve brief evidence without widening patch authority

Contract Layer (MUST): final reconciliation briefs for editorial blockers SHALL include compact source evidence when source refs can be resolved and a bounded generated-module summary when module artifacts exist. Runtime-only files and source/middle artifacts SHALL remain forbidden patch targets.

Guidance Layer (SHOULD): change `build_final_reconciliation_brief(...)` to accept optional source graph/module summary inputs, or add a separate enrichment helper that packet-builder calls before persistence.

### Decision 5: Return to final-editor step 7.3 only after this patch validates

Contract Layer (MUST): this change is complete only when source atom triage no longer creates the new Well-style false NPC blockers. Afterward, the workflow SHALL return to `toolkit-accurate-ingest-llm-builder-final-editor` task 7.3 to rerun Well through final-editor verification gates.

Guidance Layer (SHOULD): keep final-editor task 7.3 unchecked until the source atom triage patch is verified.

## Risks / Trade-offs

- Risk: table NPC extraction becomes underinclusive. Mitigation: add true NPC table fixtures and keep identity-header extraction.
- Risk: source-fidelity report loses important mechanics. Mitigation: retain mechanic/table-effect evidence outside NPC roster.
- Risk: final reconciliation brief changes affect old tests expecting empty defaults. Mitigation: preserve empty default when no evidence artifacts are supplied and add enriched-path tests separately.
- Risk: dirty worktree has multiple active OpenSpec changes. Mitigation: keep this change isolated and do not stage/commit until all three changes are validated together.

## Migration Plan

1. Add red provider-free regression tests for Well table-effect false NPC atoms and true NPC table preservation.
2. Harden source-manifest table-cell extraction.
3. Harden entity triage non-actor prefiltering.
4. Verify blueprint NPC roster and build-fidelity blockers exclude rejected non-actors.
5. Enrich final reconciliation brief evidence and generated summary with canonical-only surfaces.
6. Run targeted tests and strict OpenSpec validation.
7. Return to final-editor step 7.3 and then step 8 verification.

Rollback strategy:

- Revert the deterministic prefilters and brief enrichment helpers. Existing structural/final-editor gating remains fail-closed, so the failure mode returns to blocked builds rather than unsafe publication.
