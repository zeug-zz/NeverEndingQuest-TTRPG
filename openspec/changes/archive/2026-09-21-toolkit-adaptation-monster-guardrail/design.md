## Context

The adaptation builder already produces a complete provisional module in `tmp/adaptation-staging/<attempt>/revision_<n>`. Its current closure step scans `locations[].monsters[]`, assumes every string is a stat-block identity, and invokes `monster_builder.py --module <name>`. `monster_builder.py` resolves that option through `ModulePathManager`, so it writes to the live `modules/<name>/monsters/` directory instead of the staging tree. See `proposal.md` for the motivating failure.

The accurate-ingest materialization helper is provider-free and already provides reuse-first resolution, schema sufficiency checks, per-reference diagnostics, and encounter-seed binding. The adaptation lane uses that resolution boundary and the existing Module Builder LLM only after Python has approved the canonical identity.

## Goals / Non-Goals

**Goals:**

- Establish a deterministic semantic boundary between monster identities and encounter prose for `llm_adaptation` builds.
- Reuse accurate-ingest materialization and encounter binding as adaptation guardrails.
- Permit only canonical monster identities to reach monster closure and stat-block generation.
- Allow the LLM to complete mechanics for an approved identity using bounded source context and 5e SRD exemplars.
- Make all adaptation monster writes staging-local and verifiable.
- Search reusable artifacts comprehensively enough that exact or payload-named matches are not skipped by a small candidate cap.
- Preserve rich narrative descriptions by keeping them in location/encounter prose rather than discarding them.
- Surface exact unresolved semantic references and filesystem/materialization failures.

**Non-Goals:**

- Do not redesign the adaptation dossier, source normalization, plot generation, map generation, or NPC generation.
- Do not change legacy/non-adaptation monster closure behavior in this slice.
- Do not add a human review requirement or a new LLM identity-classification pass.
- Do not ask the LLM to classify raw prose into monster identities.
- Do not silently invent a replacement monster identity for an unresolved phrase.
- Do not permit arbitrary provider-written files or arbitrary filesystem paths.
- Do not publish or register a module before the staging tree passes all required gates.

## Decisions

### 1. Adaptation-only guardrail boundary

The packet builder SHALL invoke the new guardrail only when the build mode is `llm_adaptation`. Legacy builds continue using the existing closure path. This minimizes upstream divergence and prevents adaptation-specific semantic rules from changing established module behavior.

Alternative rejected: replacing `ensure_monster_reference_closure()` globally. That would increase merge risk and could alter existing modules that rely on its current behavior.

### 2. Source vocabulary plus deterministic canonical matching

The guardrail SHALL derive source monster candidates from bounded adaptation dossier encounter adversaries and combine them with schema-sufficient existing/bestiary/module-authorized creature identities. Generated area entries SHALL be normalized by deterministic matching: quantity prefixes and descriptive suffixes may be removed only when a canonical creature identity is unambiguous. NPCs, allies, and unmatched prose SHALL remain non-monster content and SHALL be reported when they cannot be safely relocated or classified.

The Module Builder LLM MAY generate or complete a stat block for an approved canonical identity. The generation context SHOULD include the source description, encounter role, bounded party/threat context, and a compact 5e SRD exemplar where available. The provider MUST NOT choose a replacement identity or turn an unclassified prose phrase into a combatant.

Alternative rejected: asking the provider to classify its own output. Python owns structural identity and the failure would remain nondeterministic and difficult to audit.

### 3. Reuse-first materialization with explicit generation

Resolution order SHALL be:

1. schema-sufficient artifact already in the staging module;
2. exact canonical artifact in every explicitly supplied reusable module/bestiary root;
3. descriptive or quantity-bearing reusable artifact whose JSON payload carries the exact canonical name;
4. schema-sufficient compendium artifact copied into staging;
5. provider generation for the canonical identity only, if explicitly enabled by the existing adaptation generation policy;
6. bounded unresolved diagnostic and blocked result.

The implementation SHALL not allow a fixed attempt cap to hide exact reusable matches. Candidate budgets MAY bound payload scans and diagnostics, but exact canonical filename matches across all supplied reusable roots MUST be considered before the budget is exhausted. The packet builder SHALL pass the reusable roots available to the adaptation workspace.

Every materialized artifact SHALL be verified in the staging directory after writing.

### 4. Explicit output directory for subprocess generation

`monster_builder.py` SHALL accept an explicit output directory for adaptation materialization. The closure/materialization caller SHALL pass the staging path and SHALL never pass a live module path. Generation SHALL be allowed only when the existing adaptation policy explicitly permits it for the current staging revision.

Generation SHALL be bounded to already-canonical references supplied by the caller, one request per reference per attempt, a bounded total reference count, a per-reference timeout, strict JSON/schema-sufficiency verification, and a staging-root containment check. The module name remains metadata and naming context, not the filesystem destination. If an explicit output directory is absent, legacy behavior remains unchanged.

Alternative rejected: copying files back from `modules/` after generation. That preserves the live-tree side effect and can leave orphan files after failure.

### 5. Normalized references before generic closure

The guardrail SHALL normalize or reject adaptation `location.monsters[]` values before the generic closure runs. The generic closure becomes a final consistency check for adaptation builds and SHALL NOT perform blind generation from raw prose. The final report SHALL include source refs, normalized refs, excluded non-monster entries, encounter bindings, reused/generated counts, generation policy status, SRD/context guidance status, and unresolved diagnostics.

### 6. Early failure reporting is authoritative

Any guardrail, reuse, generation, or closure early return SHALL persist the current build result and attach a bounded `failure_classification` containing failure class, group, code, failed stage, and revision eligibility. The adaptation status projection SHALL expose the concrete code without exposing raw provider payloads.

## Risks / Trade-offs

- [Risk] Deterministic phrase matching may reject a creative encounter phrase that is actually intended to be combatant content -> Mitigation: preserve the original phrase in the diagnostic and require an explicit canonical adversary in the dossier or authored area data; do not silently guess.
- [Risk] Existing adaptation artifacts may contain prose already stored in `monsters[]` -> Mitigation: normalize before closure and add fixture coverage from the Hostis failure patterns.
- [Risk] The LLM may produce mechanically poor stats for an approved identity -> Mitigation: provide SRD exemplars, validate required fields and bounded mechanical ranges, record generation input/output hashes, and keep the artifact replaceable in staging.
- [Risk] Provider generation could still be slow or unavailable for many canonical missing monsters -> Mitigation: reuse-first resolution, exact-match search, bounded candidate counts, per-reference timeout, total generation budget, and concrete retryable diagnostics.
- [Risk] Changing monster builder CLI behavior could affect callers -> Mitigation: add an optional output-directory argument and preserve the existing module-derived destination when it is omitted.
- [Risk] A failed adaptation could leave stale live artifacts from prior runs -> Mitigation: staging isolation tests, no live-tree writes in adaptation mode, and cleanup/rollback verification before publication.

## Migration Plan

1. Preserve the completed provider-free guardrail and legacy compatibility tests.
2. Generalize reusable-root lookup and wire reusable roots into the adaptation packet builder.
3. Add bounded canonical LLM stat completion with source context, SRD exemplars, staging-only output, and post-write verification.
4. Wire the guardrail before adaptation closure; keep legacy builds on the existing path.
5. Run a fresh Hostis replay with generation enabled by the active staging policy, then run module validation, readiness, gameplay, and publication checks.
6. Roll back by disabling the adaptation guardrail feature path and retaining the existing legacy closure; no live module should be promoted during a failed rollout.
