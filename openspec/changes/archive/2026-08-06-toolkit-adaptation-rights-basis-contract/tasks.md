## 1. Prompt Contract Alignment

- [x] 1.1 Update `prompts/toolkit/adaptation_author_prompt.txt` so `rights_basis` is explicitly described as a Python-owned opaque value that MUST be echoed character-for-character; replace the prose example with a canonical-token example and preserve all existing rights/review guidance.
- [x] 1.2 Update the author prompt source-contract tests to require the exact-echo instruction and reject the contradictory prose example, without changing the dossier schema or operator flag.

## 2. Provider-Free Regression Coverage

- [x] 2.1 Add a production-shaped authoring regression using `rights_basis=user_authored_uploaded_adventure`: exact provider echo passes, while a prose paraphrase produces `rights_or_provenance_mismatch` on `rights_basis`.
- [x] 2.2 Extend route/publication-boundary coverage to verify a rights-basis mismatch stops before ModuleBuilder and publication, does not consume semantic revision budget, does not fall back to legacy, and leaves module, registry, and campaign sentinels unchanged.
- [x] 2.3 Verify text-description rights basis coverage remains aligned with the Python-owned `user_submitted_text_description` value and that restricted/review-gated rights behavior is unchanged.

## 3. Live And Runtime Verification

- [x] 3.1 Run the focused provider-free author, dossier, rights, route, publication-boundary, rollback, and legacy compatibility suites with no provider/network calls.
- [x] 3.2 Run exactly one bounded GPT-5.6 author smoke using the existing redacted outcome harness; record only `ready_dossier`, `author_policy_refusal`, or `infrastructure_failure` plus safe metadata.
- [x] 3.3 Run a fresh real Toolkit upload attempt using the corrected author contract; require either verified adaptation publication or a bounded fail-closed result with no publication side effect.

## 4. Final Gates

- [x] 4.1 Compile all modified Python files, run ASCII and diff checks, verify no raw provider/source payload is persisted or exposed in the structured Toolkit status, and confirm `ENABLE_LLM_ADAPTATION` was not changed.
- [x] 4.2 Run `openspec validate toolkit-adaptation-rights-basis-contract --strict` and the full supported OpenSpec validation set; document the existing unrelated baseline failures without modifying them.
