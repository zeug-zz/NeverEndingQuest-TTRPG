# Proposal

## Why

The Study 3b adjudication confirmed ha003 was model-attributable and found that a harness stop after its contract failure left two approved scenes unattempted. This change defines the narrowly authorized continuation of that same study and ledger, preserving the first attempt and its evidence while safely completing only the two remaining scenes.

## What Changes

- MUST preserve the original Study 3b run/report, attempt, receipt, response, stop record, and complete 7,495-byte ledger prefix with SHA-256 `a522e60692c4aa2c7f622998f2ac6cb165ef02211043abf949c319858fa7fd5e`; append the adjudicated ha003 validator code and rule only as metadata, without changing prefix bytes.
- MUST permit one continuation of study ID `mise-en-scene-study3b-20261111` and ledger/lock identity `llm-staging-study3b-20261111`, gated by ruling `neq-s-study3b-adjudication-20261111`, proof of that exact prefix, the original result and spend, and the frozen scene order; protect the transition with an atomic lock and race rejection, and prohibit ledger reinitialization or replay.
- MUST attempt only `into_the_deepvault:scene:sd005-i03` then `xhalruuns_masquerade:scene:tsu001-ao02`, one attempt each, without replaying `ha003-i02`; preserve OpenRouter `openai/gpt-6-luna`, 16,384 max tokens, 720 seconds, no retry/fallback/availability GET, three attempts total, and a USD 0.05 total ceiling inclusive of the original USD 0.004085175 receipt.
- MUST treat a contract failure as a completed scene and continue to the next scene; only transport, identity, persistence, or budget `STOPPED` outcomes halt dispatch. Record validator code and rule ID as structured metadata without prose. A new protocol/harness defect marks the staging line BLOCKED and does not authorize Study 4, but does not itself halt the remaining authorized attempt; ordinary model-attributable contract failures are not reclassified as protocol defects.
- MUST require fresh all-11-check exact-head CI and a clean provider-free preflight with zero infrastructure failures on that same head before primary-only continuation. The earlier readiness/CI evidence remains historical and is not reused as the continuation gate.
- MUST retain the first metadata-only handoff and send exactly one separate metadata-only handoff after continuation. Keep raw outputs private; if both remaining scenes pass deterministic gates, submit them for independent semantic review before any owner rating.

Scope is this planning revision and the future bounded Study 3b continuation only. MUST NOT modify the original ledger prefix, first-attempt event or receipt, prior-study code/protocols/evidence/reports/verdicts, perform a provider call during planning, open Study 4, archive, merge, or expose generated prose. No shared gameplay path changes, so 1-PC and multi-PC runtime behavior is unaffected.

## Capabilities

### New Capabilities

- `tt-mise-en-scene-staging-study`: owns the isolated staging-study contract, including request/contract/hydration parity, guarded-knowledge handling, bounded execution, and privacy-safe handoff.

### Modified Capabilities

None. The new Study 3b boundary is separate; existing Study 3 capability requirements are not changed.

## Impact

The planned continuation handling and focused tests remain within the existing Study 3b runner/ledger boundary and its tests; no frozen protocol file or prior-study source is changed. The continuation appends to the same Study 3b ledger only after verifying and pinning the exact original prefix. No gameplay API, dependency, or shared runtime changes are planned.
