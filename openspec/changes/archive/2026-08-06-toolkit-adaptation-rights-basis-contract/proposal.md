## Why

The first live adaptation author request was rejected before ModuleBuilder because Python supplied the canonical `rights_basis` value `user_authored_uploaded_adventure`, while the author prompt example teaches the provider to return a prose explanation. The runtime correctly refused to publish a dossier whose Python-owned provenance metadata did not match, but the prompt and runtime contract are inconsistent.

This slice aligns the author contract with the existing strict Python authority boundary before another live Toolkit build is attempted.

## What Changes

- Require the adaptation author to echo the Python-provided `rights_basis` value exactly, without paraphrasing, translating, or replacing it with explanatory prose.
- Replace the contradictory prompt examples with canonical-token examples and explicit exact-echo guidance.
- Add a provider-free regression using the production upload rights basis and a provider-shaped dossier so this mismatch cannot recur silently.
- Preserve strict Python validation of `source_hash`, source identity, `rights_class`, review state, `adaptation_mode`, and `rights_basis`.
- Verify the corrected contract with one bounded live GPT-5.6 author smoke followed by a fresh upload-path build attempt.
- Keep policy refusal, infrastructure failure, no-downgrade routing, staging, publication, registry, campaign, and rollback behavior unchanged.

## Capabilities

### New Capabilities

- `toolkit-adaptation-rights-basis-contract`: Defines exact Python-owned `rights_basis` echoing and regression coverage at the adaptation author boundary.

### Modified Capabilities

- None. The existing adaptation author-provider contract remains strict; this slice makes its prompt and example contract executable.

## Impact

- `prompts/toolkit/adaptation_author_prompt.txt` and any mirrored author prompt contract.
- Provider-free author prompt, authoring, and route-handoff regression suites under `scripts/`.
- The bounded live author smoke and a fresh Toolkit upload attempt.
- No new GUI controls, API fields, publication paths, rights classifications, or operator flag changes.
- No changes to `model_config.ENABLE_LLM_ADAPTATION`; the existing operator setting remains authoritative.

## Non-Goals

- Do not weaken or bypass Python-owned rights validation.
- Do not treat a provider refusal or provenance mismatch as eligible for semantic revision.
- Do not add legacy fallback when adaptation is selected.
- Do not alter the separate terminal stdout/debug logging path in this slice.
- Do not modify source-fidelity extraction, ModuleBuilder generation, readiness gates, or publication transaction semantics.

## Rollout And Fallback

- Provider-free contract tests MUST pass before the live smoke is attempted.
- The live smoke MUST make at most one bounded author request and MUST record only a redacted outcome.
- If the live smoke still produces a mismatch, the attempt remains blocked and no module, registry, or campaign state may be published.
- If the provider is unavailable, the outcome is recorded as infrastructure failure; the operator flag and legacy routes remain unchanged.
- Rollback is reverting the prompt/example/test slice; no existing module or runtime state is rewritten.
