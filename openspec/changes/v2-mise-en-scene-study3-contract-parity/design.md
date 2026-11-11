# Design

## Context

See `proposal.md` for motivation and `specs/tt-mise-en-scene-authoring-projection/spec.md` for the behavior contract. The Study 3 parity/request/reference work is already present, but its current synthetic preflight does not provide a durable Study 3 allocation or real one-shot runner. The Study 1/2 `StagingClient` owns a different frozen manifest and shared ledger, so it must not be used as Study 3 state.

The reserved OpenRouter transport from commit `008cc4d4` is the required dispatch implementation. Its cited profile pins 4,096 tokens and a 30-second timeout; the current checkout still pins 4,096 tokens and uses 180 seconds. Neither profile is the approved Study 3 envelope. The adaptation therefore belongs only in the Study 3 namespace; the old client, ledger, transport behavior, protocol hashes, and evidence remain unchanged.

## Goals / Non-Goals

**Goals:**
- Persist a Study 3-only reservation before credentials or HTTP, with identity-bound ordering, durable state, a fixed cap, path confinement, concurrency control, and fail-closed cost reconciliation.
- Reuse the existing reserved one-shot OpenRouter dispatch and response sanitization while enforcing the Study 3-only 16,384-token/720-second profile.
- Make the final pre-call gate exact-SHA: all required CI checks green and provider-free preflight with zero infrastructure failures on that same SHA.
- Keep provider outputs private until independent post-study semantic review.

**Non-Goals:**
- Editing or re-pinning Study 1/2 code, protocols, tests, rate records, or evidence; using their shared ledger or changing their frozen failure history.
- Changing any Study 3 protocol/input pins, making another availability request, adding retries/fallbacks, or permitting calls before the exact-SHA gates.
- Performing implementation, publication, allocation, provider calls, or semantic review in this planning-only update.

## Decisions

1. **Keep the Study 3 contract and durable allocation isolated.** Keep the fixed identity `mise-en-scene-study3-20261110` and its ledger path independent of run ID/root so changing either cannot reset the three-attempt cap. Store reservations, results, and run artifacts only below `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3-prep/`; never point to the Study 1/2 ledger or run tree. The simplest alternative, routing through Study 2's `StagingClient`, is rejected because it binds the wrong manifest, identity, and ledger.

2. **Make the ledger durable and fail closed.** Serialize each reservation under an exclusive lock, validate the complete prior state, append the identity/scene/order/request-hash/cost reservation, and flush it durably before credential lookup or dispatch. Bind result and actual-cost receipts to that reservation. Reject traversal, symlinked roots/files, duplicate or out-of-order scenes, duplicate ledger/result files, malformed/hash-invalid state, unresolved reservations after restart, concurrent duplicate dispatch, and changed identity; never repair/reset an unsafe ledger or retry a pending attempt. Provider-free tests use temporary Study 3 roots and synthetic ledgers only.

3. **Adapt the existing reserved dispatch locally rather than creating a second transport.** After a durable Study 3 reservation, a Study 3-local `OpenRouterTransport` subclass overrides only request-profile validation for the exact 16,384-token Study 3 payload. It supplies an injected HTTP deadline adapter that delegates to the existing `_UrllibHTTP` with an effective 720-second timeout and redirects disabled, then uses the existing one-use reserved-dispatch context and `_dispatch_reserved` path. This retains delayed credential lookup, one POST, bounded response handling, and credential-echo sanitization without changing shared Study 1/2 source or constants. Do not monkeypatch globals, reuse the old client/ledger, or silently downgrade the request. Provider-free tests must assert the dispatched body and effective timeout; if the existing reserved boundary cannot satisfy them, fail closed.

4. **Use the exact approved envelope and no extra provider lookup.** Dispatch only the ordered scenes `into_the_deepvault:scene:ha003-i02`, `into_the_deepvault:scene:sd005-i03`, and `xhalruuns_masquerade:scene:tsu001-ao02`, using `openai/gpt-6-luna`, OpenRouter, `allow_fallbacks=false`, `max_tokens=16384`, and timeout 720 seconds. No retry, rerun, continuation, tool, redirect, stream, or additional availability GET is allowed. The existing request builder/protocol pins remain unchanged.

5. **Enforce the stop matrix.** Persist the reservation before dispatch. Any pre-dispatch identity failure, transport failure/timeout, missing or mismatched provider identity, or non-200 response consumes/stops the run with later scenes unspent. HTTP 200 with invalid Study 3 content consumes that scene and may proceed to the next only when the response's actual cost has been reconciled and remaining budget is safe. There is never a retry or replacement attempt.

6. **Separate estimates, reservations, and actual cost.** Retain the historical expected USD `0.0125671` and conservative USD `0.0324461` as ESTIMATES from the already-bound rate record; do not fetch availability or substitute an unverified rate. Before each POST, refuse unless the conservative remaining envelope is strictly below the USD `0.05` ceiling. Reconcile actual provider-reported cost from the one-shot response/receipt into the matching ledger result. Missing, pending, malformed, or inconsistent actual cost blocks every later dispatch; do not make a second network request to obtain it. Record any observed ceiling breach and stop.

7. **Keep output private until semantic review.** Restrict the Study 3 run root and raw response/ledger files (directory mode 0700, files 0600 where supported). Logs, exceptions, preflight/status records, and cost receipts contain only allowlisted metadata, hashes, and safe failure codes, never credentials, prompt text, or response prose. Do not self-score or present outputs as semantic findings; semantic review and any owner ratings remain independent and pending until the designated review.

8. **Make execution conditional on the same exact SHA, with no extra approval stop.** The primary may execute only after all required local gates and all 11 CI checks pass on the exact published DRAFT SHA and provider-free preflight on that same SHA reports zero infrastructure failures. Until then, do not initialize the real ledger, access credentials, or call the provider. The ruling grants conditional execution after those gates; do not add another per-step approval or pre-call Overseer review. After the three attempts or an earlier stop boundary, preserve private evidence and stop for independent post-study semantic review.

9. **Keep the existing parity and diagnostic evidence intact.** Preserve the Study 3 rule map, bidirectional mutations, three references, collect-all Study 2-copy diagnostics, and all completed task evidence. Keep the exact boundary-harness exception already recorded in task 4.1 narrow; runner code and provider-free tests stay within the Study 3 namespace. No diagnostic copy, frozen Study 1/2 artifact, or existing preliminary report is rewritten.

## Risks / Trade-offs

- **[The legacy transport profile does not match Study 3's envelope]** -> Use and test a Study 3-local adapter over the existing reserved dispatch; require the effective 16,384-token request and 720-second HTTP deadline, while leaving the legacy profile unchanged.
- **[The Study 3 adapter relies on a reserved-dispatch internal seam]** -> Pin behavior with provider-free parity tests at the exact published SHA and fail closed if that seam changes.
- **[A crash or concurrent process may leave uncertain allocation state]** -> Persist before dispatch, serialize reservation, and refuse pending/corrupt state after restart; never replay an uncertain attempt.
- **[An estimate may be mistaken for actual spend]** -> Label historical rates as estimates, keep the separate hard ceiling, and block subsequent dispatch if actual cost is absent or inconsistent.
- **[Study outputs or credentials may leak before review]** -> Restrict evidence paths/permissions and keep all logs and status reports metadata-only with credential-echo tests.

## Migration Plan

No Study 1/2 migration or rewrite is required. Create the Study 3 ledger only after the exact-SHA pre-call gates pass; all its records and outputs remain under the isolated Study 3 root. Publish only a DRAFT head, never merge, and preserve frozen protocol/evidence hashes. No extra availability request is made. Stop after the run (or an earlier stop boundary) for independent semantic review.

## Open Questions

None. The ledger scope, Study 3 transport adaptation, cost rule, pre-call gate, and post-study review boundary are fixed by the ruling.
