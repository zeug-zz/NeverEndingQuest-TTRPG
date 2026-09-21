# ADR-0031: Independent Development Fork

- Date: 2026-09-21
- Status: Accepted
- Supersedes: ADR-0002 and ADR-0030
- Superseded by: None
- Amends: ADR-0003 (rescopes upstream-first requirements)

## Context

The fork diverged by 393 commits ahead of the 2026-02-19 merge base
`c3604eb35a`. At the 2026-09-20 review, the upstream tip was `44f1458e1e`.
The fork now owns different state, provider, UI, memory, combat, and
publication architectures, so wholesale upstream merge parity is no longer a
useful design constraint. The approved rationale and evidence are recorded in
`plans/archive/independent-fork.md`; the preceding upstream review and merge plan is
archived at `plans/archive/upstream-merge-0826.md`.

## Decision

Develop the fork independently. Upstream is historical and technical reference
material only and remains read-only. There is no routine upstream fetch cadence.
Any behavior port requires a separately approved fork change, with its own
scope and verification. All pushes must be explicit pushes to `origin`.

ADR-0003 is rescoped by this decision: extension-first design remains an
internal maintainability discipline, but upstream-first preservation and merge
parity are retired. ADR-0002 and ADR-0030 are superseded by this independent
development policy.

## Retained Internal Boundaries

- Python remains authoritative for mechanical, persistence, publication, and
  campaign state.
- Runtime state writes remain atomic.
- Both single-player and TABLETOP MODE support remain internal product
  requirements.
- Extension boundaries remain useful for ownership and testability.
- Testable contracts remain required at important boundaries.
- Source and user-facing output remain ASCII-only.
- `# TABLETOP MODE:` markers document lineage and ownership without providing
  merge-compatibility guarantees.

## Remote Policy

The `upstream` remote is fetch-only and has push URL `DISABLE`. Never push to
upstream. The remote is not part of routine development; any exceptional
reference or port review must be separately approved as a fork change.

## Attribution And License

Fair Source license terms, upstream copyright notices, and third-party
attribution remain in force. Any vendored code retains its applicable license
and attribution.

## React Vendor Policy

A future upstream React snapshot may be vendored once as a fork-owned seed for
the `/client` surface. After vendoring, it is fork-owned and creates no ongoing
upstream synchronization obligation.

## Marker Policy

Existing `# TABLETOP MODE:` markers identify fork-owned lineage and integration
points. They do not promise merge compatibility. Existing markers are not
renamed solely because the fork is now independently developed.

## Consequences

- Upstream is no longer a merge lane.
- Internal authority, persistence, extension, testability, ASCII, and
  single-player/TABLETOP MODE discipline are retained.
- Future upstream behavior ports are change-scoped, separately approved, and
  verified within fork-native contracts.

## Sources

- `plans/archive/independent-fork.md`
- `plans/archive/upstream-merge-0826.md`
- `AGENTS.md`
