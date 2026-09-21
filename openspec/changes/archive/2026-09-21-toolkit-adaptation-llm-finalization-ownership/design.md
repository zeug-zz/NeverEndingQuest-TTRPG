## Context

The adaptation packet builder currently performs monster normalization and a read-only `ensure_monster_reference_closure(..., allow_generation=False)` check before publication convergence. A semantic unresolved reference returns through `_finish_adaptation_staging`, where `_adaptation_failure_classification()` marks the result terminal. The job-reporting layer and `_project_adaptation_gate_revision()` independently exclude monster failures from revision promotion. As a result, an Amphail content mismatch consumes no revision budget and never reaches the LLM auditor/revision workflow.

The desired boundary is intentionally asymmetric. The LLM may interpret source-grounded content, select among approved canonical identities, reconcile quantity/scene meaning, and propose bounded content remediation. Python remains the authority for rights, paths, staging, schemas, artifact identity, freshness, proposal validation, atomic writes, registry/campaign publication, and rollback.

## Goals / Non-Goals

**Goals:**

- Establish one deterministic canonical identity registry for every adaptation monster reference and encounter seed.
- Preserve source scene prose and structured quantity as separate content fields.
- Turn eligible content closure failures into bounded revision candidates before terminal classification.
- Feed a redacted failure packet and bounded monster-resolution contract to the existing adaptation LLM auditor/revision path.
- Use a fresh staging revision for every accepted content revision and rerun the complete pipeline.
- Keep hard safety gates and publication transaction ownership in Python.
- Provide exact Amphail coverage for `Cave guardians`, K06, K08, and K10.

**Non-Goals:**

- Do not change legacy accurate-ingest, non-adaptation ModuleBuilder, or generic closure behavior.
- Do not ask the LLM to choose arbitrary filesystem paths, emit raw patches, create schemas, or alter IDs, topology, registry state, or campaign state.
- Do not mechanically rewrite scene prose or silently resolve contradictions such as K08's quantity/prose mismatch.
- Do not increase revision budgets, retry indefinitely, or publish a partially finalized staging tree.
- Do not persist raw source excerpts, full prompts, provider responses, credentials, or arbitrary request bodies in failure packets.

## Decisions

### 1. Canonical registry is the single identity contract

Build an adaptation-only registry before closure with entries for raw references, normalized variants, approved canonical identities, source evidence, encounter/location references, and quantity. Exact existing artifacts and source-grounded canonical names are preferred. A plural/group label may resolve to a singular canonical identity only when one approved identity is unambiguous. The registry is passed to normalization, materialization, failure-packet creation, revision validation, and encounter binding so these stages cannot disagree.

Quantity is a structured field on the encounter/location reference, never part of the canonical filename identity. Scene prose is retained in bounded evidence and authored narrative; Python does not rewrite it to force a quantity match.

### 2. Content and hard failures use separate classification

A missing canonical artifact, plural/group alias, quantity/prose contradiction, or other source-grounded content gap is revision-eligible when it can be expressed through the bounded monster-resolution contract. Rights, path containment, malformed JSON, schema failure, provider/infrastructure failure, unsafe identity substitution, stale artifact identity, and transaction errors remain terminal. The classifier must receive an explicit semantic/content reason and must not infer eligibility from the word `monster` alone.

### 3. Failure packet is the only LLM input for this repair

For an eligible failure, Python builds a bounded packet containing attempt ID, revision ID, normalized unresolved reference, approved/candidate canonical identities, affected location IDs, quantity values, short redacted scene evidence, source-reference IDs, and budget state. It carries hashes/counts rather than raw source, full prompts, provider payloads, credentials, absolute paths, or arbitrary patch data. The packet is persisted atomically under the current attempt and is the only repair context exposed to the LLM auditor/revision seam.

### 4. Monster resolution is an explicit bounded operation

The finalization contract accepts one operation per revision round, such as `resolve_monster_reference`, with a Python-owned reference key, exactly one approved canonical identity, optional quantity confirmation, bounded interpretation code, and source-reference IDs. Python validates operation name, target identity, source evidence, quantity bounds, attempt/revision identity, freshness, and schema-compatible result before applying anything. The operation cannot carry a path, JSON patch, file contents, arbitrary prose replacement, registry mutation, or new identity.

The provider may request that the existing ModuleBuilder/monster materialization seam generate mechanics for an already-approved identity, but Python verifies the resulting artifact identity and schema in the fresh staging target. A provider-substituted identity is rejected and remains a concrete content failure.

### 5. Revision creates a fresh staging target and restarts the pipeline

An accepted content operation creates the next bounded project-relative staging target through the existing staging/revision helper. The prior revision is immutable evidence. The re-entry point is normalization, not a late closure patch: source packet, dossier, canonical registry, area/encounter materialization, closure, spatial/semantic convergence, readiness, gameplay, report agreement, Markdown, and publication gates run again. No live module, registry, campaign, or runtime state is changed during revision.

### 6. Publication remains Python-owned

The finalizer reports a candidate result only. Publication is allowed only when the current attempt/revision has complete content finalization, valid schema and artifact identity/freshness, rights/policy approval, all structural/readiness/gameplay/semantic/report gates passing, and the existing atomic registry/campaign transaction verifies after write. Any hard gate failure prevents publication even if the LLM claims readiness.

### 7. Legacy isolation and linked output hygiene

All new registry, failure packet, revision, and finalization behavior is guarded by the adaptation route. Legacy routes retain their existing inputs, closure, output, and diagnostics. The linked output-hygiene change supplies the output boundary used while building packets, invoking the auditor, and reporting progress; this change does not add raw logging as a debugging mechanism.

## Risks / Trade-offs

- [Risk] A broad label could be over-folded into the wrong monster. -> Mitigation: approved identity registry, exact-first resolution, bounded variant rules, source evidence, and fail-closed ambiguity.
- [Risk] K08's quantity/prose contradiction could be hidden by normalization. -> Mitigation: retain both fields and emit a diagnostic for LLM interpretation; no mechanical prose rewrite.
- [Risk] Revision could mutate the prior attempt or live module. -> Mitigation: fresh staging target, project-relative containment, immutable prior reports, and publication-last transaction checks.
- [Risk] Existing status projections disagree about monster revision eligibility. -> Mitigation: centralize content-vs-hard classification and update packet builder, gate projection, and job reporting together with cross-surface tests.
- [Risk] A provider returns a plausible but unsafe patch. -> Mitigation: explicit operation schema, canonical identity allowlist, strict bounded validation, and no arbitrary filesystem write surface.

## Migration Plan

1. Add the adaptation canonical registry and exact Amphail fixture contracts without changing legacy paths.
2. Add bounded failure packets and content-vs-hard classification at the early closure boundary.
3. Add the validated monster-resolution operation and fresh-staging revision adapter to the existing auditor/revision workflow.
4. Re-enter the full pipeline after accepted remediation and align status projections with revision budget state.
5. Run exact Amphail, existing adaptation, publication, revision, provider-safety, and legacy regression suites.
6. Enable only through the adaptation route; a failed rollout is reverted by disabling the adaptation finalization seam, with no live artifacts promoted.
