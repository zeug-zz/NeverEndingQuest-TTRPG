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

This is the task 6.10 software PASS only. It is not a live N2 PASS, CI result, protected merge, or post-merge observation. Tasks 6.2 and 6.9 remain unchecked. The historical N2 failure report and its uncertainty about image outcome remain unchanged. The accepted diagnosis concerns the later observation and does not establish historical handshake headers. No browser, listener, provider, gameplay, booking, seed, or live network run was performed here.

After the PR is green and protected-merged, follow the separate task-ledger post-merge procedure: clean checkout, direct short-shell full-import and managed P1 preflights; then exactly one booked zero-provider P1 Chrome observation requiring Connected over WebSocket. Stop and report any failure, and stop for Overseer review after the observation. N4 public-tunnel/network checks must exercise WebSocket-blocked fail-closed behavior; no polling fallback is added.
