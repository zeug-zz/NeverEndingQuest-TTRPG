# N2 player WebSocket handshake software verification

Ruling: `neq-n2-origin-fix-20261110`.

The player Socket.IO client now explicitly uses `transports: ["websocket"]`, retaining its existing path, cookie, reconnect, and build/protocol authentication options. The regression verifies WebSocket-only configuration, fail-closed behavior without polling, and the real Engine.IO WebSocket handshake through the in-process ASGI app, including valid credentials/origin/host and rejection cases. The handshake tests include offline/network/provider/socket/DNS tripwires. No server authentication, Host, Origin, CSRF, or session checks were changed.

The setup evidence defect was in the harness: `page.evaluate` serializes its callback, while the safety callback depended on a module-scoped status set. Making that safety callback self-contained fixes the real production evaluate path; tests exercise the serialized callback against authenticated Disconnected markup and verify masking, exact-origin, logout, password, and known-status protections. Early protocol metadata uses shared `readPlayerVersion` when available and remains null when unknown, without skipping the normal Connected wait. WebSocket diagnostics correlate bounded CDP WebSocket-created, handshake-request, and response events by request ID, retaining only safe status/transport and Origin/Host/session-cookie booleans; raw URLs, query values, request IDs, and headers are not persisted.

Primary software verification (2026-11-10):

- `node --test web/frontend/e2e/*.node-test.mjs` — 88/88 passed.
- `PYTHONPATH=. .venv/bin/python -m unittest -q scripts.test_player_websocket_handshake scripts.test_player_access scripts.test_player_client_assets scripts.test_player_route_inventory` — 45 tests passed.
- `npm --prefix web/frontend run typecheck` — passed.
- `npm --prefix web/frontend test -- --run` — 29 passed.
- `npm --prefix web/frontend run build` — passed; ignored `dist/` refreshed, not tracked.
- `npm --prefix web/frontend run test:e2e -- --list` — 11 listed only; no browser run.
- `npm --prefix web/frontend run test:n2-gate -- --dry-run --observe-handshake` — passed.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-react-player-vertical-slice --strict` — passed.
- `python3 scripts/check_ascii_compliance.py --summary-only` — 910 files, zero violations.
- `git diff --check` — passed.
- Changed-path pre-commit — ASCII and Gitleaks passed; Bandit had no eligible files.

## Status boundary and remaining work

This is the task 6.10 software PASS only. It is not a live N2 PASS, CI result, protected merge, or post-merge observation. At the software-only checkpoint, tasks 6.2 and 6.9 remained unchecked. The historical N2 failure report and its uncertainty about image outcome remain unchanged. The accepted diagnosis concerns the later observation and does not establish historical handshake headers. No browser, listener, provider, gameplay, booking, seed, or live network run was performed here.

After the PR is green and protected-merged, follow the separate task-ledger post-merge procedure: clean checkout, direct short-shell full-import and managed P1 preflights; then exactly one booked zero-provider P1 Chrome observation requiring Connected over WebSocket. Stop and report any failure, and stop for Overseer review after the observation. N4 public-tunnel/network checks must exercise WebSocket-blocked fail-closed behavior; no polling fallback is added.

## Primary follow-up evidence (2026-11-10)

The primary reviewed the inert-only `--observe-handshake` capture at `tmp/router-rollout/v2-network/n2-handshake-observe/n2-20261110T004057000Z-eb64c9ca/` (`primary-review.json`, `run.json`, `request-diagnostics.jsonl`, `provider-attempt-ledger.jsonl`, `release.json`, and `SHA256SUMS`). The screenshot showed canonical authenticated Connected state, the Acheron sheet, masked blank controls, and no credentials. Clean build `c8d0b185` / `558e2b58c68f704273f8995140934c72`, Chrome 157.0.8103.50, protocol 1, WebSocket GET 101, and Origin-present/matches, Host-matches, and session-cookie-present all passed. The active ledger showed zero reservations and refusals at all required checkpoints; monitor/header activation only; owned stop, primary-exclusive bind-and-close, and booking release passed. This is PASS for the inert observation only, not a full N2 PASS.

The separately authorized straight Chrome P1 gate at `tmp/router-rollout/v2-network/n2-chrome/p1-agent-chrome-20261110T004340Z-b290967b/` failed. The primary reviewed `run.json`, `scenarios.jsonl`, `provider-attempt-ledger.jsonl`, `release.json`, `sandbox-state-review.json`, and the image. Three per-check assertions passed (party coherence, request-ID deduplication, transcript ordering), but the active-PC selection assertion failed: expected Acheron, observed empty. The canonical post-teardown tracker named Acheron as active (revision absent/null); the screenshot showed Connected and the Acheron label but a masked blank selector and empty controls. The offline production-helper diagnosis in `tmp/n2/chrome-gate-p1-preflight/masking-diagnosis.json` showed `sanitizeSetupScreenshotPage` clearing every select's selected index and `afterEach` reusing the mutated page; this strongly implicates screenshot-masking harness state interference and is not evidence of an accepted product active-PC mechanics defect. No fix or retry is authorized pending Overseer diagnosis review, and masking/authentication proofs must not be weakened.

P1 recorded 1 provider reservation (`POST api.openai.com/v1/images/generations`) and 0 refusals under the 30-attempt cap; response, resolved model, and image outcome remain unknown, with no pricing claim. This is distinct from the inert capture's zero-provider ledger. Playwright had 3 passed, 1 failed, and 7 unexecuted of 11; the three scenarios with passing Chrome checks aggregate BLOCKED because Firefox is missing. Overall gate counts were 0 PASS / 1 FAIL / 10 BLOCKED. The seven unexecuted scenarios include all three managed lifecycle scenarios. P4 was not run after the P1 failure, and required Firefox checks were omitted/BLOCKED. Owned managed stop, primary-exclusive bind-and-close probes for 8360/8370, and booking release passed. Overall N2 remains FAIL/incomplete, task 6.2 remains open, and no N3, lifecycle, P4, or content retry was performed.
