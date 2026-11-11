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

## Ruling `neq-n2-locator-rerun-20261110` locator audit

Audited every production `hasText`/`getByText` call in the N2 spec and production E2E helpers, plus related role-scoped alert text. The offline locator fixture and node-test model are test fixtures, not production helpers; excluded from the production audit and not changed.

| Source / line | Locator intent and bounds | Substring collision assessment |
|---|---|---|
| `n2-gate.spec.ts:516,522,555` | `.transcript-message` filtered by a unique run-scoped marker (`N2_REPEATED_REQUEST_`, `N2_HOST_TRANSCRIPT_`) | Marker is a whole unique probe string, not a shared natural-language label. Parent also contains author text, so exact matching the whole parent would be incorrect. Disjoint markers; no competing probe prefix/suffix overlap. |
| `n2-gate.spec.ts:737,739,788` | Exact complete busy/ready status labels; intended game input status | `exact: true`; source `App.tsx:489-495` confirms these full status strings. Busy and ready labels are distinct. |
| `n2-gate.spec.ts:782-794,849` | Busy receipt regex `/This input was not queued/` | Source `App.tsx:585-586` contains this phrase only in the full busy receipt. Other nearby receipt strings do not contain it; the narrower phrase does not match the busy-state label. No overlapping competing text observed. |
| `n2-gate.spec.ts:846,898,907,922,930` | Exact `Connected` status; `n2-gate.spec.ts:905,928` exact `Disconnected` status | `exact: true`; `App.tsx:560-577` confirms these are complete connection labels. No prefix/suffix status-label collision. |
| `n2-gate.spec.ts:851,854` | Transcript parent filtered by run-scoped rejected/accepted marker | Full probe markers are intentionally contained in transcript text; markers are unique and distinct (`N2_BUSY_INPUT_ONE_`, `N2_BUSY_INPUT_ACCEPTED_`). Parent includes other text, so exact whole-parent matching is inappropriate. No marker overlap. |
| `managed-lifecycle.mjs:265` | Exact `Connected` after login | `exact: true`; full status as in `App.tsx:568`. No collision. |
| `managed-lifecycle.mjs:418` | `.transcript-message` filtered by unique `N2_INSTANCE_CHANGE_<runId>` marker | Marker is run-scoped; parent may include author text, so substring filter is intentional. No competing marker overlap. |
| `managed-lifecycle.mjs:421` | Regex for pending `Sending input for <character> at revision <n>...` | Matches the pending-only status shape at `App.tsx:496-499`; receipt text has different phrasing. The regex bounds the dynamic character/revision parts and terminal ellipsis; no competing status shape. |
| `managed-lifecycle.mjs:425,427` | Exact `Disconnected` status | `exact: true`; complete label at `App.tsx:572`. No collision. |
| `managed-lifecycle.mjs:430-435` | Alert-role scoped uncertainty phrase for pending input | Pending uncertainty is an alert at `App.tsx:501-507`. Receipt uncertainty uses `role="status"` at `App.tsx:508-510` and its text in `receiptMessage` at `App.tsx:595-598`; therefore it cannot match this `getByRole("alert")` locator. No current duplicate within the alert boundary. |
| `managed-lifecycle.mjs:473,475` | `.transcript-message` filtered by run-scoped lifecycle marker | Marker is unique to the scenario/run and parent author text makes whole-parent exact matching wrong. No marker overlap. |
| `login-player.mjs:15` | Exact `Connected` after canonical login | `exact: true`; complete status label at `App.tsx:568`. No collision. |

The only confirmed ambiguous label was `Hit points` versus `Maximum hit points`, already corrected by `sheet-locator.mjs:5` using `/^Hit points$/`; the fixture at `sheet-locator.chrome-fixture.mjs:16` deliberately asserts the old substring ambiguity. No additional production substring collision was found. This is a source audit only; it does not authorize a live rerun or change the historical verdict, Task 6.2, or merge status.
