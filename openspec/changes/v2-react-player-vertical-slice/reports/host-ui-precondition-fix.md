# Host UI precondition fix

Cause: the host gameplay input is disabled until `game_started`; requiring it to be editable rejected a freshly loaded host UI.

Change: host usability now requires attached output/input and an enabled Start Game button (connected socket), or an already-running game. Input enabled state is informational; no probe is filled or submitted.

Builder checks: focused Node tests, frontend typecheck, strict OpenSpec validation, and `git diff --check`.

Primary verification pending.


Primary verification (software only): Node 94/94; typecheck; strict OpenSpec valid; ASCII 910/0; git diff --check clean. Primary reviewed the real host UI screenshot (Connected, enabled Start Game, input disabled until game start) from p1-relogin-20261110T101740Z-c79d6a0d. Ruling neq-n2-lifecycle-hostui-diagnose-20261110. Game is deliberately not started (would dispatch providers). No live rerun/CI/merge claimed; task 6.2 open.
