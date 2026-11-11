# Design

## Context

See `proposal.md` and `specs/tt-mise-en-scene-staging-study/spec.md` for the motivation and contract.

The selected worktree contains the active Study 3 parity change and its source. `scripts/mise_en_scene/llm_staging_study3/contract.py` validates public base IDs from the bound Study 3 inputs, while `newrequest.py` renders and checks those IDs in the actual request. `newhydration.py` currently delegates canonical loading and delta projection to `scripts/mise_en_scene/llm_staging_study2/hydration.py`; that helper creates audience knowledge from source rows but only projects scalar source values into fixture facts. Study 3b addresses the adjudicated parity seam in its own namespace. The only permitted private-response access is the primary-only, in-memory extraction of the exact preserved ha003 Study 3 response marker for the attribution diagnostic; no response prose is persisted, logged, disclosed, or semantically scored.

## Goals / Non-Goals

**Goals:**

- Make one hash-bound per-scene source-fact inventory authoritative for the Study 3b request-visible records, claim-reference allowlist, and hydration parity check.
- Preserve exact source identity and provenance, keep guarded facts non-claimable, and leave protected unknowns unknown.
- Bind the final run, accounting, approval, and privacy boundary to a distinct Study 3b identity.

**Non-Goals:**

- Modify or repair Study 1, Study 2, or Study 3 code, protocol, fixtures, reports, evidence, or verdicts.
- Change shared gameplay behavior, Study 3's existing capability contract, or the approved scene inputs.
- Inspect or decode any raw response except the exact minimum Study 3 marker material required for the explicitly authorized primary-only in-memory attribution diagnostic; publish or semantically judge raw output.

## Decisions

1. **Keep all corrections in a new Study 3b namespace.** Add `scripts/mise_en_scene/llm_staging_study3b/` and Study 3b-only tests/configuration. Read existing Study 3 bindings and the existing Study 2 hydration/transport implementation as immutable sources. Do not patch `newrequest.py`, `contract.py`, `newhydration.py`, Study 2 hydration, or any earlier protocol/evidence. The simplest alternative, fixing the Study 2 hydrator in place, is rejected because it would alter a frozen prior-study source.

2. **Use one canonical inventory and compare normalized records, not just ID sets.** For each fixed scene, load only hash-verified canonical bindings and retain every source fact's ID, audience, status, value, source pointer/reference, and provenance. Derive the request-public IDs and contract allowlist from this inventory; compare each request-public record with its hydration representation using an explicit field mapping. Preserve audience metadata even where the legacy fixture schema represents it in `audience_knowledge` rather than a fixture fact. The simpler alternative, maintaining request, validator, and hydration lists independently, is rejected because it permits the observed drift.

3. **Adjudicate the original Study 3 ha003 request attribution without exposing content.** Request primary inspection of the exact preserved offending Study 3 response marker and recorded transport request hash. Reconstruct the actual dispatched Study 3 request from its hash-bound inputs, require its canonical hash to match that recorded transport hash, then compare the exact marker in memory with the reconstructed request and canonical guarded annotations. Read only the minimum private marker material for this diagnostic; do not alter, copy, persist, or disclose it, and do not score semantics. Emit only the request/marker/annotation hashes, necessary IDs, and boolean/null result plus an ambiguity code. If the request hash or marker match is ambiguous, return indeterminate and make no model-attribution claim. Provider-free tests use synthetic mutations and never inspect private response data.

4. **Separate Study 3b allocation and lock identity from every prior run.** Use the fixed ID `mise-en-scene-study3b-20261111`, run root `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3b/`, preparation root `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3b-prep/`, and lock identity `llm-staging-study3b-20261111`. The append-only ledger binds identity, exact scene order, request hash, reservation, result, and actual-cost receipt; no prior ledger is opened for allocation, copied, reset, or replayed. Reuse the original ledger-gated one-shot OpenRouter transport from commit `008cc4d4` through a Study 3b-local policy adapter; do not implement, copy, replace, or bypass the transport or reservation gate. Use injected fake transport in provider-free tests.

5. **Keep the authorized envelope fixed and fail closed.** Bind the ordered scenes `into_the_deepvault:scene:ha003-i02`, `into_the_deepvault:scene:sd005-i03`, and `xhalruuns_masquerade:scene:tsu001-ao02`; OpenRouter model `openai/gpt-6-luna`; 16,384 max tokens; 720-second timeout; one attempt per scene, three total; no retry, fallback, or availability GET; and USD 0.05 maximum actual cost. Persist each reservation before credential access or dispatch. A timeout, quota/outage, non-200 response, unresolved reservation, or missing/inconsistent actual-cost receipt stops the run; no replacement attempt is made under this authorization.

6. **Bind the primary run and handoff to one exact head.** Run-fence approvals cite `neq-s-study3-adjudication-20261111` and bind the Study 3b ID, protocol/config hashes, and final head without seeking a new owner approval. Require all 11 CI checks and provider-free preflight with zero infrastructure failures on that same head before the primary initializes or uses the real allocation. Keep raw output private until independent review; send one metadata-only Overseer handoff with provenance, safe per-scene statuses, hashes, and actual-cost receipt. Stop at the first protocol defect and do not open Study 4.

## Risks / Trade-offs

- **A Study 3b projection can drift from the legacy gate representation.** Mitigate with complete-record comparisons and mutation tests across all three scenes; any mismatch blocks dispatch.
- **The preserved response marker or recorded request hash may not establish request-time guarded annotation.** Return an indeterminate boolean/status with hashes only; do not claim model attribution or inspect more response content.
- **An interrupted or failed provider attempt can leave spend uncertain.** Keep the durable reservation pending and stop; never reset, replay, retry, or dispatch a later scene without reconciled cost.
- **Exact-head evidence can become stale.** Bind approvals, CI results, provenance, and preflight to the identical final head and reject any mismatch.

## Migration Plan

No prior-study migration is required. Create the Study 3b ledger only after exact-head approvals and clean preflight pass. A reserved or uncertain attempt remains accounted for and is never rolled back or reset; stop for independent review after completion or an earlier fail-closed boundary. No merge, archive, or Study 4 closeout is part of this change.
