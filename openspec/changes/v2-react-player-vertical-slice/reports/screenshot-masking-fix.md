# N2 screenshot masking harness software verification

Ruling: `neq-n2-masking-fix-and-rerun-20261110`.

The primary visually reviewed `tmp/n2/masking-fix/setup-evidence-chrome-mask.png`. The correction is harness-only: read-only safety checks identify form/editable/recognized credential elements, which Playwright masks directly with `caret: 'initial'`. No value, text, selection, focus, or style mutation or rollback is used. Exact-origin, authenticated-shell, logout, no-password, and known-status proofs remain unchanged. Exact restoration was rejected because rollback could erase concurrent updates.

Primary software verification:

- `node --test web/frontend/e2e/*.node-test.mjs` — 89 passed, 0 failed.
- `node --test web/frontend/e2e/setup-evidence.chrome-fixture.mjs` — 1 passed; actual Chrome HTML, attributes, style, values, selection, editable content, and focus stayed invariant across successful, repeated, failed, and unsafe captures. Pixel-level mask assertions passed.
- The separate jsdom Node regression verified concurrent-update preservation.
- `npm --prefix web/frontend run typecheck` — passed.
- `npm --prefix web/frontend test -- --run` — 29 passed.
- `npm --prefix web/frontend run build` — passed.
- `npm --prefix web/frontend run test:e2e -- --list` — 11 listed only.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-react-player-vertical-slice --strict` — passed.
- `python3 scripts/check_ascii_compliance.py --summary-only` — 910 files, 0 violations.
- `git diff --check` — passed.

This is primary-verified software evidence only. No live rerun, CI, or merge has occurred. Per the newest ruling, proceed only after green exact-head CI/protected merge and clean-merged full-import plus P1/P4 preflights; then book Chrome P1 followed by P4, stopping on any FAIL. Limits are 30 attempts, 3 hours, and USD 1 per run; no content retry and at most three harness-failure iterations. Product, budget, or safety failure requires cleanup and report, then STOP. Firefox remains BLOCKED, task 6.2 remains open, and no N3 work is authorized.
