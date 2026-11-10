# Reload re-login fix

Cause: the N2 gate treated a page reload as preserving the authenticated session, while the player requires re-login after reload.

Change: the busy-input and refresh-reconnect reload paths now call the canonical `loginPlayer` helper before their existing shell/connection assertions. Draft-clearing, transcript, busy-receipt, and offline/online reconnect assertions remain unchanged. The task wording records that reload requires re-login and session restore is out of scope.

Builder checks: Node 90/90, typecheck, e2e list (11), strict validation, diff check passed.

Primary verification (software only): `node --test web/frontend/e2e/*.node-test.mjs` 90/90; typecheck passed; `test:e2e --list` 11 tests; strict OpenSpec valid; ASCII 910 files 0 violations; `git diff --check` clean. Ruling: neq-n2-reload-relogin-20261110. Historical FAIL (p1-locatorfix-20261110T070938Z-5d55fb32) retained. No live rerun, CI or merge claimed; task 6.2 remains open.
