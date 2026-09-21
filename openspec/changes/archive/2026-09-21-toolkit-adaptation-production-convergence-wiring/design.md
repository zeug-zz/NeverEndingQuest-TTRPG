## Context

The completed adaptation convergence and monster-guardrail changes expose provider-free seams and staging-safe contracts. The completed runtime-unification change routes eligible upload and text-description inputs into adaptation, but the later convergence stage expects a callback that production entry points do not currently supply. The guardrail also accepts `allow_canonical_monster_generation` only as Python-owned provenance, while the operator path has no explicit setting that can provide it.

The design must preserve the existing route boundary, staging identity, report agreement, legacy fallback rules, and Python ownership of monster identity and module structure. See `proposal.md` for motivation and the capability specs for normative behavior.

## Goals / Non-Goals

**Goals:**

- Provide one shared production callback for upload and text-description adaptation builds.
- Make deterministic convergence the default and reserve provider calls for bounded repairable blockers.
- Reuse the existing convergence validation, failure classification, AI client factory, GPT-5 parameter resolver, monster guardrail, and publication transaction.
- Expose an explicit canonical-monster-generation opt-in with a safe disabled default.
- Preserve current attempt/revision/source/staging identity across every report.
- Make route-level behavior testable without provider or live-module writes.

**Non-Goals:**

- Reimplement convergence, semantic authority, monster closure, or publication gates.
- Add a second provider/router architecture or a new GUI mode.
- Change legacy accurate-ingest or direct ModuleBuilder behavior.
- Let the provider write files or decide canonical identities, topology, schemas, registry entries, or campaign state.

## Decisions

### 1. One shared production callback adapter

The production adaptation runtime will expose one callback adapter consumed by both upload and text-description packet-build paths:

```text
eligible adaptation route
    -> authoring and staged ModuleBuilder output
    -> bounded convergence callback
       -> deterministic blocker/request inspection
       -> no repairable blocker: success, no provider call
       -> repairable blocker: bounded provider proposal
       -> Python validation and staging-safe apply
    -> existing final gate composer
    -> existing finisher/publication transaction
```

The packet builder remains the convergence owner. Route and worker code only provide the callback and preserve the existing handoff envelope. This avoids separate upload/text implementations and keeps legacy calls from requiring adaptation arguments.

Alternative rejected: making the packet builder treat a missing callback as success. That would make a required production stage silently disappear and would weaken the fail-closed contract.

### 2. Deterministic-first provider use

The callback will inspect the bounded current-stage request and validation context before invoking a provider. Unique destination matches, already-resolved semantic authority, reusable monster artifacts, and other deterministic outcomes will complete without an LLM call. Only an allowlisted repairable blocker will reach the provider.

The provider boundary will use the existing client factory and configured model parameter resolver. Direct GPT-5-family requests will retain the repository's current reasoning/verbosity and sampling-parameter rules. The callback will pass only bounded request fields, source-reference IDs, canonical IDs, topology summaries, approved monster IDs, and scalar provenance. Raw source text, credentials, arbitrary paths, registry state, and campaign state will not cross the boundary.

Alternative rejected: calling the provider for every adaptation build. That adds latency and cost where Python already has a deterministic result and increases the surface for unnecessary proposal drift.

### 3. Shared failure and identity handling

Provider exceptions and malformed proposals will flow through the existing bounded convergence result contract. The adapter will not invent a second failure taxonomy. Every returned result will retain the current attempt ID, attempt number, revision number, source hash, staging-relative path, failure class, and retry eligibility.

The route will preserve selected adaptation authority: an adaptation failure remains an adaptation failure and cannot fall through to legacy generation. The existing finisher remains the only stateful publication boundary.

### 4. Python-owned canonical generation opt-in

Add `ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = False` to the operator configuration surfaces. The route will copy the setting into the bounded Python-owned adaptation provenance only when it is exactly `True`, as `allow_canonical_monster_generation=True`.

The guardrail will continue to require all of the following before generation:

- adaptation mode is active;
- the reserved staging target is in the eligible building state;
- the explicit provenance opt-in is true;
- the monster identity is already in the Python-approved canonical set;
- every supplied reusable root and compendium source has been checked first;
- the generated payload passes exact identity and schema verification.

Provider output cannot set or elevate the opt-in. Legacy builds never receive the adaptation provenance field.

Alternative rejected: enabling generation whenever `ENABLE_LLM_ADAPTATION` is true. Adaptation routing and canonical stat generation have different risk and cost profiles, so generation remains a separate explicit opt-in.

### 5. Minimal host hooks and extension ownership

The shared callback and provenance helper belong in the adaptation runtime extension. The upload route wrapper and text adaptation worker receive thin, adaptation-guarded hooks marked with `# TABLETOP MODE:` where host files require changes. The packet builder's existing optional callback parameter remains the seam used by tests and production.

No new GUI selector is required. The operator controls adaptation and canonical generation through configuration, and existing job status/report surfaces expose bounded outcomes.

### 6. Verification and rollout boundary

Provider-free tests will exercise both production entry paths with an injected callback and fake generation seam. They will prove:

- disabled and legacy routes do not invoke the callback;
- enabled deterministic passes do not call a provider;
- enabled repairable blockers call the bounded callback and apply only validated operations;
- provider failures remain staging-local and do not fall back to legacy;
- canonical generation remains disabled by default and accepts only approved identities;
- all reports share one attempt/revision/source identity;
- registry and campaign writes remain owned by the existing post-gate finisher.

An optional live smoke is a separate, explicit operator action. It will use the configured GPT-5.6 route, one bounded request at a time, project-local staging, and redacted result reporting.

## Risks / Trade-offs

- [Risk] The callback could accidentally call the provider on every build. -> Make deterministic no-blocker success an explicit first branch and add a no-provider tripwire test.
- [Risk] Route and text worker behavior could diverge. -> Use one callback adapter and run the same contract suite against both entry paths.
- [Risk] Canonical generation could be enabled unintentionally. -> Use a separate strict boolean defaulting to `False`, copy it only through Python-owned provenance, and add invalid/missing flag tests.
- [Risk] A stale callback result could apply to a newer staging revision. -> Revalidate attempt, revision, source hash, and staging identity at the existing convergence boundary.
- [Risk] Provider failure could trigger legacy generation. -> Preserve selected adaptation authority and assert no-downgrade behavior at route level.
- [Risk] A provider-generated monster could still change identity. -> Reuse the existing approved-ID and exact-payload-name checks before schema closure.
- [Risk] A live smoke could mutate runtime state. -> Require project-relative staging and protected live-state hash/sentinel checks; stop before publication unless the explicit smoke contract requests a full publish test.

## Migration Plan

1. Add the two capability contracts and provider-free route/provenance test fixtures.
2. Implement the shared deterministic-first callback and pass it only through enabled adaptation upload/text paths.
3. Add the separate canonical-generation opt-in with default `False`; verify disabled behavior first.
4. Run provider-free route, convergence, guardrail, publication, legacy, and full adaptation regression suites.
5. Run an explicit bounded live author/convergence smoke only after provider-free gates pass.
6. Keep `ENABLE_LLM_ADAPTATION=False` and canonical generation opt-in `False` as the release default. The operator may enable them for controlled testing after validation.
7. Roll back by disabling the flags and restarting/reloading configuration; retain staging reports and do not alter published modules or runtime state.

## Open Questions

None. The production callback policy is deterministic-first with bounded LLM proposals only for genuinely repairable blockers.
