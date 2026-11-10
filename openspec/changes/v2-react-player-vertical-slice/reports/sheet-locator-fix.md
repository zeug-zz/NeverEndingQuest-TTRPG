# N2 sheet locator correction

Builder iteration 2 under `neq-n2-masking-fix-and-rerun-20261110` corrected only the harness assertion. The sheet contains both `Hit points` and `Maximum hit points`; substring matching selected both. The shared Chrome/Firefox scenario now uses an exact-label regular-expression locator and retains the strict count of one. The product is unchanged.

Primary software verification passed: Node regressions 90/90; standalone offline Chrome fixture 1/1; frontend typecheck, frontend tests (29), build, and E2E listing (11 tests) passed; strict OpenSpec validation passed; ASCII compliance reported 910 files and zero violations; `git diff --check` passed. The changed-path pre-commit initially raced the build while regenerated ignored `dist` assets were being replaced and failed with `FileNotFound`. A serial rerun after the build passed ASCII/Gitleaks; Bandit had no eligible files. No source fix or check bypass was used.

Primary visually reviewed the retained P1 screenshot at `tmp/router-rollout/v2-network/n2-chrome/p1-maskfix-20261110T021514Z-1c402907/capture/screenshots/sheets-initiative-combat-busy-state-player-a-chrome.png`: it shows distinct `Hit points` 20 and `Maximum hit points` 20 labels, with Connected status and Acheron active. The exact-locator correction is harness-only and does not alter product behavior.

The historical P1 run remains 4 passed, 1 failed, and 6 unexecuted; all 11 Firefox checks are BLOCKED, and P4/lifecycle remain unexecuted. The ledger recorded 1 reservation and 0 refusals; cost and model outcome remain unknown. Teardown, port checks, and release passed. Preserve this historical failure and uncertainty. Task 6.2 remains OPEN. No live rerun, CI, or merge is claimed.

Checks:

- `node --test web/frontend/e2e/*.node-test.mjs`
- `node --test web/frontend/e2e/sheet-locator.chrome-fixture.mjs`
- `npm --prefix web/frontend run typecheck`
- `npm --prefix web/frontend run test:e2e -- --list`
- `git diff --check`

Strict OpenSpec validation, ASCII compliance, and changed-path pre-commit outcomes above are recorded as primary verification; the pre-commit rerun was serial after build completion.
