## Context

The existing adaptation author boundary already computes rights metadata in Python, passes it through the attempt envelope, and compares the returned dossier against that metadata before any ModuleBuilder or publication work. The live failure exposed a contract gap: the prompt constrains exact echoing for `source_hash`, but its `rights_basis` example is explanatory prose while the runtime expects a canonical token.

The relevant constraints are defined in the proposal and the new rights-basis capability spec. This design preserves the existing strict no-relabel boundary rather than changing policy semantics.

## Goals / Non-Goals

**Goals:**

- Make the provider-facing contract unambiguous for every Python-owned rights basis.
- Keep the existing exact identity comparison and fail-closed behavior.
- Exercise the production upload and text-description basis values in provider-free tests.
- Verify one bounded live author request before a fresh Toolkit build is attempted.
- Keep public diagnostics bounded and publication side effects impossible on mismatch.

**Non-Goals:**

- Do not accept provider paraphrases as equivalent rights metadata.
- Do not change rights classification, review gating, semantic revision policy, or legacy fallback behavior.
- Do not add a GUI option, new API field, provider retry loop, or publication transaction.
- Do not address general stdout/debug logging in this slice.

## Decisions

### Decision 1: Keep the canonical basis Python-owned

The route and text adapters remain the only sources of `rights_basis`. The author request will expose the value through the existing Python-owned attempt metadata and will explicitly require exact echoing. The provider remains a creative author only; it cannot derive or rewrite policy metadata.

**Alternative rejected:** accepting a provider-written prose explanation. That would make the provider an authority over a policy field and would require a new normalization/equivalence policy that is unnecessary for this fix.

### Decision 2: Align prompt examples with the runtime contract

The author prompt will state that `rights_basis` is an opaque canonical value and MUST be copied character-for-character. Examples will use a canonical token rather than a prose explanation. The schema remains unchanged because it already permits the canonical bounded string.

**Alternative rejected:** adding a second `rights_basis_token` field. That would widen the dossier schema and create two fields that can drift without solving the immediate contradiction.

### Decision 3: Preserve strict failure classification

The existing mismatch guard remains authoritative. A mismatch produces the existing bounded `rights_or_provenance_mismatch` outcome, remains non-retryable for the semantic revision budget, and stops before staging publication. The route and job-reporting mappings remain unchanged.

**Alternative rejected:** silently replacing the provider value after parsing. That would make the live response appear valid without proving that the provider followed the contract, and would weaken the diagnostic signal this slice is intended to protect.

### Decision 4: Test the live-shaped boundary, not only synthetic prose fixtures

Provider-free tests will construct a Python preflight with `user_authored_uploaded_adventure` and exercise both an exact-token dossier and a prose-paraphrase dossier. Prompt source-contract tests will require the exact-echo instruction and reject the old prose example. Route tests will verify that a mismatch does not invoke ModuleBuilder, consume semantic revision budget, or mutate module, registry, or campaign state.

### Decision 5: Keep live validation bounded and opt-in

The live smoke will issue at most one author request, use the existing GPT-5.6 parameter resolver, and emit only a redacted outcome classification. It will not run publication. A fresh Toolkit upload build is a separate post-fix verification step and must run only after provider-free tests pass.

## Risks / Trade-offs

- **[Risk]** A provider may still paraphrase despite the stronger prompt. **Mitigation:** the strict guard remains fail-closed, and the production-shaped regression makes the failure diagnosable before a user build.
- **[Risk]** A prompt-only correction can fail under a future model or prompt edit. **Mitigation:** source-contract tests lock the exact instruction and canonical examples; the live smoke is a release gate for this change.
- **[Risk]** A strict mismatch can block an otherwise creative dossier. **Mitigation:** preserve the existing policy boundary and fail before publication rather than weakening Python authority.
- **[Risk]** Live verification could expose source or provider content. **Mitigation:** keep the request bounded, use the existing redaction/reporting path, and record only safe outcome metadata.
- **[Risk]** Prompt changes could alter unrelated dossier quality. **Mitigation:** change only the rights-basis instruction/example and rerun the existing author, dossier, route, and publication contract suites.

## Migration Plan

1. Update the author prompt and mirrored prompt contract tests.
2. Add provider-free exact-token and paraphrase regression cases.
3. Run the focused authoring, route, no-downgrade, publication-boundary, and protected-state suites.
4. Run one bounded live author smoke and record only its safe classification.
5. Run a fresh upload-path build and verify completion or a bounded failure with no publication side effect.
6. If validation fails, revert the prompt/test slice; no module, registry, campaign, or source-upload migration is required.
