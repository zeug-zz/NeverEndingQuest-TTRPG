# ADR-0003: Upstream-First Extend-Do-Not-Replace Policy

- Date: 2026-03-10
- Status: Amended
- Supersedes: None
- Superseded by: None
- Amended by: ADR-0031

## Context
Past merge regressions occurred when local modifications replaced upstream structures rather than extending them.

## Decision
Adopt upstream-first integration rules:
- Preserve upstream UX and structure intact.
- Add narrow hooks only when needed.
- Avoid broad rewrites in host files.

## Consequences
- Lower risk during upstream sync.
- Better behavioral parity with upstream features.
- Slightly more indirection, but substantially safer merges.

## Amendment (ADR-0031)

ADR-0031 retires upstream-first preservation and merge parity: upstream is now
historical and technical reference material only. Extension-first design remains
an internal maintainability rule for this fork:

- Prefer extension files and narrow hooks for new behavior.
- Keep host-file edits deliberate, marked, and reversible.
- Do not preserve a host implementation solely for upstream compatibility.

Any upstream behavior port requires a separately approved fork change.

## Sources
- `AGENTS.md`
- `openspec/changes/archive/2026-02-17-exit-only-gui-shutdown/`
- `adrs/0031-independent-development-fork.md`
