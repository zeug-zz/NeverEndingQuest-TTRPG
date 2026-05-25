# ADR-0030: Selective Upstream Patch Porting

- Date: 2026-05-26
- Status: Accepted
- Supersedes: None
- Superseded by: None

## Context

This repository extends upstream [MoonlightByte/NeverEndingQuest](https://github.com/MoonlightByte/NeverEndingQuest)
with tabletop multiplayer features via a plugin architecture (clearly marked `# TABLETOP MODE:` hooks,
separate extension files, runtime activation by party size). Many core files have diverged substantially
from upstream. Wholesale branch merging is no longer practical — it risks introducing conflicts or
regressions for no benefit when the upstream change is already covered by our own work.

The plugin architecture and upstream-first discipline (ADR-0002, ADR-0003) remain in force as internal
code conventions. This ADR adds a practical decision rule for *when* to accept an upstream commit
versus skip it.

## Decision

**Inspect upstream commits individually and selectively port what adds value.** Do not merge upstream
branches wholesale. Keep `upstream/main` as a read-only reference.

### Patch Selection Policy

1. **Inspect upstream commits one by one.** Review monthly or when GitHub shows upstream activity.
2. **Classify each commit:**
   - `already covered` — fork has equivalent or stronger behavior (skip).
   - `port manually` — valuable fix; reconcile and apply the minimal code change.
   - `ignore` — not relevant to fork (skip).
   - `investigate` — unclear impact (flag for later).
3. **Port when upstream touches:** security fixes, data corruption fixes, save/load reliability,
   provider/API compatibility, critical browser/runtime bugs.
4. **Do not blindly merge when upstream touches** areas that are heavily modified here —
   `web/web_interface.py`, `web/templates/game_interface.html`, `main.py`, combat flow, character
   state, module runtime, prompt/validation contracts. These require manual reconciliation.
5. **Track skips and ports** in the Upstream Sync Log in `AGENTS.md`.

### First Skipped Commit

- `c149109` (2026-05-25): fix(#122) reconnect browser to live game and stop input busy-spin.
  - **Already covered:** Combat busy-spin fixed by TABLETOP MODE idle-input hardening (2026-03-17).
  - **Already covered:** Browser reconnect handled by `request_status` → `status_response` flow.

## Consequences

- Upstream is monitored but not mechanically merged. Patch volume should remain low.
- SP mode should be smoke-tested periodically.
- The plugin architecture and TABLETOP MODE discipline (ADR-0002, ADR-0003) continue unchanged.
