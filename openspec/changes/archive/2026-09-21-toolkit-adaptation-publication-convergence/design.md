## Context

The adaptation monster guardrail produces staging artifacts, but a playable adaptation can still fail downstream spatial, semantic, content, or report-agreement gates. Existing spatial normalization, semantic-authority, readiness, gameplay, and publication utilities are the source of truth and MUST be reused rather than replaced. This change adds one bounded finalization boundary rather than another independent validator.

## Goals / Non-Goals

**Goals:**

- Add one adaptation-only convergence boundary before final readiness/publication evaluation.
- Give the LLM a bounded opportunity to propose whitelisted content repairs and canonical semantic resolutions for the current staging revision.
- Reuse the existing spatial topology normalizer and semantic-authority builder.
- Let the Module Builder LLM propose resolutions for genuinely ambiguous destination phrases and other explicitly repairable content blockers so normal source-backed adaptation does not require manual intervention.
- Keep Python authoritative over canonical IDs, topology, provenance, validation, and final gate status.
- Produce one staging revision that is schema-valid, semantically resolvable, gameplay-auditable, and publishable.
- Stop after a bounded number of finalization attempts and persist one actionable blocker report if the module remains unsafe.

**Non-Goals:**

- Do not rewrite the ModuleBuilder or generic legacy closure.
- Do not use the LLM to invent locations, coordinates, connectivity, NPC authority, monster identities, IDs, or schema structure.
- Do not weaken schema, gameplay, readiness, semantic, or publication gates.
- Do not change monster identity/materialization behavior except consuming its completed staging output.
- Do not mutate live module files before all gates pass.
- Do not allow arbitrary LLM file patches; every repair MUST use a whitelisted operation and Python-owned target.
- Do not retry indefinitely or let a degraded narrative report masquerade as a passing playable module.

## Decisions

### 1. One convergence boundary, existing utilities underneath

The packet builder or finisher will call a small adaptation-only orchestration seam. That seam consumes the completed monster-guardrail staging revision, invokes existing spatial normalization and semantic-authority enrichment, asks the LLM for a bounded repair proposal only when deterministic checks leave a whitelisted repairable blocker, applies the validated proposal in staging, and then reruns readiness/gameplay/publication checks. This avoids duplicating spatial or semantic logic and keeps the host hook minimal.

Alternative rejected: adding independent validation logic to the adaptation packet builder. That would create competing topology and semantic truths.

### 2. Spatial truth remains Python-owned

Python determines whether an edge is a valid grid edge, logical area connection, or blocker. The LLM is never allowed to edit coordinates or connectivity. Non-adjacent authored links are reclassified only when the existing topology contract makes the interpretation unambiguous.

Alternative rejected: asking the LLM to repair map coordinates. Coordinate and connectivity changes are structural state and must be deterministic.

### 3. Semantic authority precedes ambiguity resolution

The pipeline first builds canonical location and destination vocabulary from authored artifacts. Unique matches resolve deterministically. Only unresolved ambiguity is sent to the Module Builder LLM, with a bounded phrase, candidate IDs, source excerpts, and topology summaries.

Alternative rejected: sending every destination phrase to the provider. This increases cost and permits nondeterministic changes where Python already has a clear answer.

### 4. LLM proposes; Python validates and applies

The LLM response is parsed as a bounded proposal containing an allowed operation, one canonical target or target field, confidence, rationale code, source-reference IDs, and a bounded replacement value where applicable. Allowed operations SHALL be explicitly enumerated by the convergence contract. Python rejects unknown IDs, low confidence, unsupported source references, topology contradictions, structural field edits, multiple candidates, extra fields, arbitrary paths, and malformed output. Accepted repairs are persisted with provenance and input/output hashes.

The LLM MAY propose:

- one canonical destination alias for a bounded ambiguous phrase;
- bounded narrative completion for an approved authored entity or encounter;
- a canonical stat completion request whose identity has already passed the monster guardrail.

The LLM MAY NOT directly edit coordinates, connectivity, IDs, schemas, monster identity, NPC authority, registry state, or live files.

### 5. Failure, retry, and rollback are staging-local

Every convergence stage writes atomic reports under the current attempt/revision. An accepted proposal creates a new bounded staging revision or an atomic revision update; provider failure or rejected proposals leave the prior staging artifacts intact. The loop has a fixed maximum number of finalization attempts, records each proposal decision, and prevents promotion if the final gate set does not pass. Live module files are touched only after all final gates pass.

### 6. Publication is the end-state contract

The convergence loop does not declare success after monster closure alone. It must rerun schema validation, spatial checks, semantic authority, readiness, gameplay probes, and publishability. A module is promotable only when all required gates pass and reports identify the same attempt/revision.

Adaptation source fidelity SHALL remain visible as provenance and diagnostic evidence. It SHALL not block an intentionally rewritten adaptation solely because the output does not preserve literal source structure, provided structural, mechanical, semantic, gameplay, and publication gates pass.

### 7. The finalizer is a resolver, not an authoring replacement

The Module Builder remains responsible for producing the initial rich module. The convergence finalizer exists only to close bounded, diagnosable gaps in the current staged output. It SHALL not regenerate the whole module, replace the source dossier, or create a second competing module truth.

### 8. Rollout, bounded failure, and promotion contract

The finalization budget is fixed for each convergence invocation: three finalization attempts, one accepted operation per round, and a 30-second timeout for each operation. These are deterministic bounds; the convergence loop MUST NOT retry without limit. The operator's current revision setting is `LLM_ADAPTATION_MAX_REVISIONS=1`; the revision runner clamps values to its implemented hard maximum of two. Revision and finalization budgets are separate and both remain bounded.

`ENABLE_LLM_ADAPTATION` MUST be a strict boolean. Missing, invalid, or `False` values resolve to the explicit legacy accurate-ingest route. The release-safe default is OFF: `model_config.py` sets the flag to `False`, matching `ENABLE_LLM_ADAPTATION_DEFAULT=False`. An explicit enabled or selected adaptation route is authoritative and MUST NOT silently downgrade to legacy. Existing tests and explicit operator overrides may still enable the route for controlled rollout.

Provider timeout, quota, unavailability, malformed output, or rejected output produces a bounded failure class and report, leaves the current staging revision unchanged, and MUST NOT mutate live modules, the registry, or campaign/runtime state. Only an explicit retry that is still eligible under the budget may run. To roll back the lane, the operator sets `ENABLE_LLM_ADAPTATION=False` and restarts or reloads configuration as required. Future uploads then use legacy routing; the prior staging revision and its evidence remain available, and accepted staging changes remain staging-local until promotion.

When the attempt budget is exhausted, or a real gate blocker cannot be repaired, the pipeline persists one bounded terminal convergence report containing attempt/revision/source identity, reason, budget state, failure class, bounded diagnostics, and `next_revision_eligible`. The candidate remains non-publishable and is available only for an explicit later retry; no promotion occurs.

Promotion has one exact boundary. It is allowed only when convergence reports `status=ready`, every consumed report matches the current attempt, revision, and source identity, and the complete final gate set reports `playable_status=pass`, `publishable_status=pass`, report-agreement status `pass`, and no blockers. The convergence orchestrator and gate composer are candidate evaluators only: they MUST NOT register, publish, or mutate campaign/runtime state. The existing Python-owned publication path owns the final promotion of that passing staging revision.

## Risks / Trade-offs

- [Risk] LLM proposals could be plausible but wrong. -> Python requires canonical IDs, source evidence, topology compatibility, bounded confidence, whitelisted operations, and deterministic rejection.
- [Risk] The finalizer could become an unbounded retry loop. -> Use a fixed attempt budget, per-call timeout, per-operation budget, and one terminal blocker report.
- [Risk] The LLM could over-edit rich source adaptations. -> Give it only bounded blocker context and whitelisted target fields; keep Python as the only structural writer.
- [Risk] Provider outage delays adaptation builds. -> Reuse deterministic unique matches first; persist a retryable provider failure without mutating live state.
- [Risk] Spatial reclassification could hide authored intent. -> Preserve logical edges and emit changed-edge provenance; never silently delete ambiguous edges.
- [Risk] Existing reports may be stale. -> Require current attempt, revision, source hash, and convergence report identity before readiness/publication consumption.
- [Risk] Legacy behavior could regress. -> Guard the orchestration by adaptation mode and retain existing legacy call paths and defaults.

## Migration Plan

1. Implement provider-free spatial, semantic, and blocker-classification convergence helpers and focused fixtures for the Hostis failure shape.
2. Add the bounded finalization proposal contract, whitelisted repair operations, attempt budget, and provider failure handling behind the adaptation convergence stage.
3. Apply accepted proposals only to staging and rerun the relevant checks after each repair.
4. Run schema, readiness, gameplay, semantic, and publication gates against the final staging revision only.
5. Promote a passing staging revision through the existing publication path.
6. If convergence fails, persist the terminal blocker report and leave the staging revision available for a later explicit retry; legacy builds remain available.

## Follow-up Slice: Semantic Authority Collision Hardening

The initial convergence implementation correctly reuses the shared semantic-authority builder, but two data-shape cases require a compatibility-preserving hardening slice before the adaptation lane can be considered complete:

1. Authored aliases are canonical authority seeds. They MUST resolve as exact aliases, but token windows synthesized solely from an alias string MUST NOT become independent player-facing destination blockers unless the same phrase is separately observed in player-facing authored evidence. This prevents an alias such as `The Empty Village Road Square` from manufacturing unresolved blockers for `empty village road` and `village road`.
2. Location IDs can be local to an area rather than globally unique. Semantic authority MUST use an area-scoped internal identity when indexing records, while retaining the raw `location_id` as a compatibility field. A duplicate raw ID MUST NOT cause location names, aliases, NPC authority, or shortform anchors to be overwritten by whichever area is processed last.

Python remains authoritative for both decisions. Exact aliases, area identity, candidate uniqueness, ambiguity, provenance, and report freshness are deterministic. No LLM resolution is added to this slice, and no live module or publication state is changed.

## Follow-up Slice: Production Destination-Resolution Closure

This corrective slice closes the production wiring gap for the already-specified ambiguous-destination behavior. It reuses the existing convergence callback and finalization safety contract; it does not create a new finalizer or a second publication path.

### Boundary and bounded request

Before invoking the callback, production convergence MUST build current semantic authority from the source manifest, normalized packet, source graph, and staged module. It MUST construct a bounded `validation_context` containing only:

- `attempt_id`, `revision_id`, and current `source_hash`;
- one unresolved phrase and its blocker reference;
- bounded candidate records with area-scoped canonical IDs, display names, and area provenance;
- source-reference IDs and a compact topology summary;
- the allowed operation list, confidence threshold, `operation_budget=1`, and `timeout_seconds=30`.

The explicit provider request MUST identify the request as destination resolution and carry that `validation_context` without raw provider history, arbitrary file paths, or unrestricted module content. The callback MUST receive this request only for the adaptation convergence lane. Legacy accurate-ingest, concept-builder, direct ModuleBuilder, single-player, and other non-adaptation paths MUST receive no convergence metadata or provider seam.

### One-operation-per-round loop

The existing convergence loop remains bounded at three finalization attempts. Each round permits at most one accepted operation. Python MUST validate the returned operation against the current attempt, revision, source identity, area-scoped canonical target, source evidence, topology, confidence, and the explicit whitelist. The only operation in this closure slice is `resolve_destination_alias`; no regex, best-candidate, or arbitrary narrative fallback is permitted.

### Staging application and gate continuation

An accepted operation MUST be applied atomically to the current staging revision, with provenance and input/output hashes persisted. The semantic authority MUST then be refreshed from staging, followed by relevant semantic checks and the complete schema, spatial, readiness, gameplay, report-agreement, and publication gate set. Finisher/publication continuation is allowed only when current reports agree on attempt, revision, and source identity and all hard gates pass.

### Failure and rollback

Provider timeout, unavailable provider, malformed or rejected output, stale context, unsupported target, insufficient evidence, topology conflict, or remaining ambiguity MUST leave the prior staging revision unchanged and persist a bounded blocker. No live module, registry, campaign, or runtime state may be mutated. The current staging revision remains available for an explicit later retry subject to the same budgets.

This slice does not regenerate the module, change monster finalization, or create another OpenSpec change. It only closes the production callback/request seam for destination resolution within this existing publication-convergence change.
