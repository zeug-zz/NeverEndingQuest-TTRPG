# N2 Chrome + Firefox gate evidence (task 6.2)

Build: origin/main 939bba76 (clean, detached). Browsers: Player A system Chrome,
Player B Playwright 1.65.0 Firefox 159.0, host UI in a separate Chrome context.

Test-environment condition (Overseer ruling neq-n2-firefox-p1-run1-20261111,
decision 1): Firefox's own content sandbox crashes when nested inside the nono
sandbox ("Target crashed" on newPage). The test browser environment sets
MOZ_DISABLE_CONTENT_SANDBOX, MOZ_DISABLE_GMP_SANDBOX, MOZ_DISABLE_RDD_SANDBOX and
MOZ_DISABLE_SOCKET_PROCESS_SANDBOX to 1. This affects only the test client; NEQ
Host/Origin/CSRF/auth rules and the nono profile are unchanged.

| Run | Party | Evidence | Result | Provider ledger lines |
| --- | --- | --- | --- | --- |
| p1-ff-20261111T020626Z (historical) | 1 | tmp/router-rollout/v2-network/n2-firefox/p1-ff-20261111T020626Z | FAIL busy-input (harness: cross-page .or locator), 5 PASS / 5 BLOCKED by fail-fast; fixed in PR 141 | - |
| p1-ff2-20261111T023456Z | 1 | tmp/router-rollout/v2-network/n2-firefox/p1-ff2-20261111T023456Z | PASS 11 / FAIL 0 / BLOCKED 0 (22 checks) | 10 (cap 30) |
| p4-ff-20261111T023550Z | 4 | tmp/router-rollout/v2-network/n2-firefox/p4-ff-20261111T023550Z | PASS 11 / FAIL 0 / BLOCKED 0 (22 checks) | 11 (cap 30) |

Each run: OD-6 preflight report with zero infrastructure failures at the exact
SHA; booking per run; teardown verified, ports 8360/8370 free; booking released.
Provider identity is unknown (receipt-derived extractor); this is not evidence of
zero provider calls. Together with the Chrome-only P1/P4 runs
(a-report-026/027) every Chrome and Firefox check passed for 1-PC and 4-PC.
