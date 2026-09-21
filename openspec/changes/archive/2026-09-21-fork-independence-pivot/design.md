# Fork Independence Pivot - Design

## Context

The fork's relationship to upstream changed materially since ADR-0030
(2026-05-26): the fork has diverged by hundreds of commits along its own
architecture (multi-PC tabletop authority, reconcile-first state guards,
two-plane memory, accurate-ingest/publication gates, GPT-5.6 Luna routing),
while upstream invested in different directions (typed model registries,
agentic combat, NPC voice, Responses API/headless transport, React surfaces).
`plans/upstream-merge-0826.md` is the previous upstream plan; its stated exit
condition ("remain open until upstream synchronization is no longer useful") is
now met. `plans/independent-fork.md` records the approved lock decisions for the
pivot.

## Goals / Non-Goals

**Goals:**

- Make independent fork governance the canonical repository policy.
- Preserve useful internal architecture discipline without treating upstream
  parity as a design constraint.
- Leave a durable, discoverable ADR record explaining why the 2026 upstream
  development branch was not merged.
- Keep the change documentation-only, reversible, and free of data migrations.

**Non-Goals:**

- No runtime, provider, combat, memory, UI, or module/data changes.
- No upstream fetch, merge, or push.
- No archival of the old upstream plan in this change (deferred to
  `fork-final-upstream-sweep`).
- No rework of historical change logs or archived OpenSpec changes.

## Baseline And Evidence

Recorded at plan creation and verified against the live repository during
task 1.1:

| Item | Value |
|---|---|
| Review date | 2026-09-21 |
| Fork HEAD | `c4b16311` (`main`) |
| Origin/main | `dd51a846` (fork one commit ahead) |
| Merge base with upstream | `c3604eb35a` (2026-02-19) |
| Fork commits ahead of merge base | 393 |
| Local `upstream/main` ref | `c3604eb35a` (stale; not fetched) |
| Upstream remote tip per 2026-09-21 review | `44f1458e1e` (2026-09-20) |
| Upstream push URL | `DISABLE` |
| Worktree at plan creation | clean except untracked `plans/independent-fork.md` |

The local upstream ref being behind the recorded remote tip is expected:
routine fetching stops with this pivot. Task 1.1 records drift or corrections
rather than fetching upstream.

## Decisions

### Architecture Boundary

The fork owns its runtime contracts: Python mechanical, persistence,
publication, and campaign-state authority; multi-PC tabletop contracts;
reconcile-first state guards; memory, diary, and story behavior;
accurate-ingest and publication gates; GPT-5.6 Luna provider routing; and the
legacy facilitator host. Upstream becomes reference material only. There are no
architectural behavior changes in this change; the design concern is
documentation coherence.

### ADR Transition

- ADR-0031 supersedes ADR-0002 and ADR-0030.
- ADR-0002 and ADR-0030 are marked `Superseded` with `Superseded by: ADR-0031`;
  historical rationale and review history are preserved.
- ADR-0003 is marked `Amended` with `Amended by: ADR-0031`: extension-first
  design remains an internal maintainability rule; upstream-first preservation
  and merge parity are retired.
- `adrs/index.md` adds ADR-0031, adds an `Amended` entry to the status legend,
  updates the status entries, and records the new supersession relationships.

### Documentation Synchronization

Active guidance is updated in one pass so the policy is stated consistently:

- `openspec/config.yaml` - project context and proposal rules (remove
  merge-safe framing, upstream-preservation guidance, and the merge-safety
  review requirement; retain MUST/SHOULD layering, Python ground truth, atomic
  JSON, ASCII-only output, and SP/MP compatibility; add fork-ownership and
  approved-port guidance). The stale OpenRouter router "Current initiative"
  block is replaced with the fork independence initiative because the file's
  project context is being rewritten and the old initiative is obsolete.
- `openspec/frontier_builder_profile.md` - remove the merge-safe evolution
  style preference.
- `AGENTS.md` - overview reframe; plugin-architecture guidance reframe; upstream
  sync policy, sync log, and legacy merge guidelines replaced with a Fork
  Independence Policy referencing ADR-0031; origin-only push safety and
  upstream never-push rules preserved.
- `README.md` - fork relationship wording; upstream and fork links retained.
- `CONTRIBUTING.md` - fork relationship wording; marker and extension guidance
  retained as lineage documentation.

### Scope Boundaries

- Deferred to `fork-final-upstream-sweep`: the closing review ledger and
  archival of `plans/upstream-merge-0826.md`. The ledger must record the final
  port outcomes (#399, #161/#162, and the #240 inspection), and the plan's
  Gate 1 forbids archiving the plan before the sweep completes. The plan task
  outline listed both under the first change; this design intentionally moves
  them to the sweep change so this change is independently completable and
  archiveable.
- Excluded from the stale-reference audit: `memory-bank/**` (deprecated legacy
  context, read-only by default), historical change-log entries inside
  `AGENTS.md` (for example the "Recent Changes" section), `docs/operations/`
  historical plan snapshots, and `openspec/changes/archive/**`.

### Marker And Remote Policy

`# TABLETOP MODE:` markers identify fork lineage, ownership, and integration
points. They no longer promise merge compatibility, and existing markers are not
renamed. The `upstream` remote remains fetch-only reference with its push URL
disabled; all pushes remain explicit to `origin`.

### License And Attribution

Fair Source license terms, upstream copyright notices, and third-party
attribution remain in force. ADR-0031 records that any future vendored upstream
code (for example a one-time React snapshot for `/client`) must retain license
and attribution and creates no synchronization obligation.

## Risks / Trade-offs

- Risk: guidance becomes internally contradictory across files. Mitigation:
  single-pass update of all active guidance files plus a stale-reference scan in
  task 4.3.
- Risk: historical decisions get erased instead of superseded. Mitigation:
  superseded ADRs keep their rationale; only status metadata and supersession
  links change.
- Risk: scope creeps into runtime files. Mitigation: task 4.4 verifies the diff
  touches only governance/documentation artifacts.

## Rollback

Revert the documentation changes. No runtime migration, schema change, or data
recovery is required.
