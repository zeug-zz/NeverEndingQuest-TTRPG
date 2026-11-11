# Design

## Context

See `proposal.md` and `specs/tt-mise-en-scene-staging-study/spec.md` for the motivation and contract.

The initial Study 3b run consumed the ha003 attempt and stopped with two approved scenes unattempted. The adjudication confirms ha003 was model-attributable and identifies a runner defect: contract failure stopped the study instead of completing that scene and continuing. The exact original ledger prefix is 7,495 bytes with SHA-256 `a522e60692c4aa2c7f622998f2ac6cb165ef02211043abf949c319858fa7fd5e`. Study 3b now requires a one-time continuation of that same ledger, not a new run identity or allocation.

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

3. **Keep the original Study 3 attribution and first-run records immutable.** The adjudication has confirmed the guarded marker was present in the hash-verified request, so ha003 is model-attributable, not a new protocol defect. Preserve its run/report, event, receipt, response, stop record, and ledger bytes. Append only a metadata supplement for validator code `GUARDED_MARKER_IN_PUBLIC_DELTA` and rule `S3-GUARDED-CONTENT-MARKERS`; do not rewrite the original event or disclose prose.

4. **Use a one-time append-only continuation transition on the existing ledger.** Keep ID `mise-en-scene-study3b-20261111`, run root `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3b/`, preparation root `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3b-prep/`, and lock identity `llm-staging-study3b-20261111`. Before append, pin and verify both original prefix length 7,495 and SHA-256 `a522e60692c4aa2c7f622998f2ac6cb165ef02211043abf949c319858fa7fd5e`, the original ha003 result, its reconciled USD 0.004085175 spend, stopped state, and next scene `into_the_deepvault:scene:sd005-i03`; also bind ruling `neq-s-study3b-adjudication-20261111`. Acquire an exclusive atomic lock before rechecking these facts and appending the single-use transition. A mismatch or competing transition fails closed. Never reinitialize, reset, replay, or mutate any prefix byte. Provider-free race tests use single-process threads, not multiprocessing.

5. **Keep the remaining allocation and model envelope fixed.** The only remaining ordered scenes are `into_the_deepvault:scene:sd005-i03` and `xhalruuns_masquerade:scene:tsu001-ao02`, one attempt each; ha003 already consumed one of three total attempts. Keep OpenRouter `openai/gpt-6-luna`, 16,384 max tokens, 720-second timeout, no retry/fallback/availability GET, and USD 0.05 maximum total actual cost including the initial receipt. Contract failures complete their scene and continue. Only transport, identity, persistence, or budget STOPPED outcomes halt dispatch. Store validator code and rule ID as structured metadata without prose. A new protocol/harness defect marks the staging line BLOCKED and does not authorize Study 4, but does not itself halt the remaining authorized attempt; an ordinary model-attributable failure remains a scene result, not a protocol defect.

6. **Require fresh same-head gates for the primary continuation.** Before continuation, require fresh evidence of all 11 CI checks green on the exact final published head and provider-free preflight with zero infrastructure failures on that same head. Earlier CI/readiness evidence is historical and cannot satisfy this gate. No frozen protocol file is changed. Preserve the original metadata-only handoff and send exactly one separate continuation handoff with provenance, prefix/transition proofs, safe per-scene statuses, structured validator metadata, and reconciled total cost. Keep raw output private; if both remaining scenes pass deterministic gates, submit them for independent semantic review before any owner rating.

## Risks / Trade-offs

- **The original ledger prefix could be altered or two continuations could race.** Verify the pinned byte length and SHA-256 under an exclusive atomic lock before appending; reject any mismatch or already-used transition. Test competing attempts with provider-free threads.
- **A contract failure could be confused with a stopped transport or a new harness defect.** Test the explicit outcome categories: contract failures complete and continue; only transport, identity, persistence, or budget STOPPED outcomes halt; new protocol/harness defects block the staging line.
- **The exact-head evidence could be stale after the continuation fix.** Require fresh all-11 CI and zero-infrastructure-failure preflight on the same final published head; do not reuse the historical readiness record.

## Migration Plan

Do not create or reinitialize a Study 3b ledger. After fresh exact-head CI and clean preflight pass, verify and pin the immutable original prefix and append the single authorized continuation transition. A reserved or uncertain attempt remains accounted for and is never rolled back or reset; stop dispatch only for a specified STOPPED outcome. Preserve the first handoff and send one separate continuation handoff. No merge, archive, or Study 4 execution is part of this change.
