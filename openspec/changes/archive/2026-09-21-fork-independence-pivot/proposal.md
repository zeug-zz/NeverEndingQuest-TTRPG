# Fork Independence Pivot

## Why

NeverEndingQuest-TTRPG and MoonlightByte/NeverEndingQuest now have incompatible
runtime, state-authority, provider, UI, memory, combat, and publication
architectures. The fork is 393 commits ahead of the 2026-02-19 merge base
(`c3604eb35a`) while upstream has continued 537 commits along its own
development branch from the same base. Maintaining merge-safe downstream
behavior creates review and design cost without preserving useful
compatibility, and the exit condition recorded in `plans/upstream-merge-0826.md`
("remain open until upstream synchronization is no longer useful") is now met.

## Objective

Make NeverEndingQuest-TTRPG an independently developed fork whose only upstream
relationship is historical and technical reference, while retaining attribution,
internal architecture discipline, and the approved final behavior sweep as a
separate implementation change (`fork-final-upstream-sweep`).

## What Changes

- Add `adrs/0031-independent-development-fork.md`.
- Supersede ADR-0002 and ADR-0030 by ADR-0031; rescope ADR-0003 to internal
  extension discipline only.
- Update `adrs/index.md` statuses, status legend, and supersession map.
- Update `openspec/config.yaml` project context and proposal rules, and replace
  the stale "Current initiative" block with the fork independence initiative.
- Update `openspec/frontier_builder_profile.md` style guidance.
- Update `AGENTS.md`: reframe the project overview and plugin-architecture
  guidance, replace the ADR-0030 upstream sync policy, Upstream Sync Log, and
  legacy upstream merge guidelines with a Fork Independence Policy referencing
  ADR-0031, and keep origin-only push safety rules.
- Update `README.md` and `CONTRIBUTING.md` fork-relationship wording while
  preserving upstream attribution links.
- Record the independence baseline as durable evidence in `design.md`.
- Mark `plans/independent-fork.md` as approved with its OpenSpec implementation
  tracking referenced.

## Capabilities

### New Capabilities

- `independent-fork-governance`: the repository identifies as an independent
  fork, retains internal architecture discipline without upstream parity, and
  removes routine upstream synchronization obligations.
- `fork-adr-supersession-record`: ADR-0031 exists, ADR-0002 and ADR-0030 are
  superseded, ADR-0003 is rescoped, and the ADR index stays consistent.
- `fork-documentation-source-of-truth`: `AGENTS.md`, `README.md`,
  `CONTRIBUTING.md`, `openspec/config.yaml`, and
  `openspec/frontier_builder_profile.md` carry coherent independent-fork
  guidance.
- `fork-upstream-reference-policy`: the upstream remote stays read-only and
  inert, ports require approved fork changes, and deferred closing artifacts are
  explicitly scoped to the sweep change.

### Modified Capabilities

- None. This change introduces new fork-governance capabilities and does not
  modify requirements of existing `openspec/specs/` capabilities.

## Non-Goals

- No wholesale upstream merge and no cherry-pick of the upstream development
  branch.
- No runtime provider, combat, memory, startup, module-builder, installer, or UI
  replacement.
- No module, saved-game, character, campaign, or runtime state migration.
- No removal of Fair Source license terms, upstream copyright notices, or
  attribution for vendored code.
- No React `/client` implementation; the React seed remains a future change.
- No archival of `plans/upstream-merge-0826.md` and no final review ledger; both
  belong to `fork-final-upstream-sweep` after the approved behavior ports are
  verified.
- No edits to deprecated `memory-bank/**` legacy context, historical change-log
  entries inside `AGENTS.md`, historical ops snapshots under `docs/operations/`,
  or archived OpenSpec changes.

## Impact

- Runtime impact: none. This is a documentation and governance change; no code
  paths, schemas, or persisted state are modified.
- SP/MP compatibility impact: none; both modes retain their existing routing and
  behavior.
- Attribution and license impact: preserved; ADR-0031 records ongoing Fair
  Source, copyright, and vendored-code attribution obligations.
- Reversibility: revert the documentation changes; no migration or data recovery
  step exists.

## Rollout And Fallback

Documentation-only behavior. Review ADR wording and updated active guidance
before archive. If review rejects the policy, revert the governance changes; no
gameplay state or runtime data is involved.
