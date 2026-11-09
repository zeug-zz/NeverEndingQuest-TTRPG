# Study 2 Step-(a) Primary Verification Packet

## Scope and authorization

S2.1-S2.4 preparation evidence only. No generation, provider/network calls, GETs, credential/key reads, or new approvals occurred. The actual study ledger/approvals are absent; initialization without pins must refuse before writes. Publication head/green CI remain pending; PR127 was not updated. Three owner approvals and Overseer review are still required before any study execution.

Study 1 remains a frozen envelope FAIL: semantic review is N/A, there are no owner ratings, and this is not capability proof. Preserve all failures; do not describe the study as never having failed.

## S2 task trace

- **S2.1 — complete:** separate protocol/delta-only contract and strict validation. Primary contract/schema note: 60 tests passed.
- **S2.2 — complete:** deterministic no-write hydration/full gate; 67 staging tests and all three hand-assembled references passed the real deterministic gate.
- **S2.3 — complete:** approval fence/ledger negative tests; 80 focused staging tests passed. No real network.
- **S2.4 — complete:** offline sizing, exact frozen-study-1 preservation, and this review packet. No execution authorization.

R11/R12 trace: S2.1-S2.3 are preparation and provider-free authorization-fence requirements; S2.4 records the frozen envelope, sizing, verification, and review boundary. None authorizes generation or owner ratings.

## Sizing and frozen evidence

Tokenizer sizing used the clearly labeled approximation `ceil(UTF-8 bytes / 3)`: scene estimates L=1284, 1288, 1319; corresponding input counts 19699, 16199, 17322. Largest L=1319 yields proposed `max_tokens=6144`, `timeout_seconds=360`. These are proposed cap values for owner approval, not authorization.

Verified historical availability rates: prompt `1e-7`, completion `5e-7`. Three-scene cost estimates are `.0050419`, `.0046919`, `.0048042`; total `ESTIMATE=.0145380` (estimate, not spend). Exact historical raw file: 829400 bytes, SHA-256 `d94...dc13` (verified exact hash recorded in primary audit). Configuration SHA-256 `2b70041e`; manifest `b08afb1bd64c2eecbf4b386e14460b79dc23f5425b6e0c9488552f604cb09358`; sizing report `aefc888cda2de1dc0aab722cd9a696a9daee5642f886825c5667c42cb158935b`. Protocol/runtime frozen file sets and full hashes matched before/after. Independent `primary-prep-audit.json` verifies exact 16 protocol/54 runtime files, exact 7 manifest role hashes, unchanged full frozen hashes, and three actual reference gates PASS (semantic/owner PENDING; scene BLOCKED).

## Primary runs and corrections

Primary logs: `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2/final-focused-primary.log` (86 tests, 2.534s); `final-offline-primary.log` (196 tests, 8.306s; 159 baseline + 37 added); `final-mapping-primary.log` (276 tests, 14.553s); `final-clean-checkout-primary.log` (isolated 37 tests, 1.370s). Materializer `--check`, ASCII 922/zero, strict validation, and diff check passed.

Corrections and retained failures: an initial clean fixture resolved the wrong Python and failed for missing `jsonschema`; the lexical-venv-path rerun exposed a test-listing-exists bug. Both failure logs were retained; the corrected isolated clean run passed 37 tests. The primary run also caught and fixed `is_byok` boolean receipt compatibility, with negative counter-boolean tests. S2.4 routing changed from haiku to heavy test-fix plus heavy usage-fix recording. Do not erase or omit these failed attempts.
